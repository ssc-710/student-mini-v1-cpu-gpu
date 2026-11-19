// gatesim: zero-delay, two-state, event-driven replay of a routed gate netlist.
//
// The program file is produced by scripts/student_mini_gatesim.py from the
// routed Verilog netlist and the standard-cell Liberty functions.  The
// stimulus is the cycle-by-cycle port trace recorded from the RTL execution
// of the same workload; every recorded output is compared at the same cycle.
// Toggle counts and high/low durations of every cell pin over each measured
// window are written as SAIF for OpenROAD read_saif.
//
//   gatesim <program> <saifmap> <stimulus> <out-dir> [--begin N] [--windows i,j,...] [--stop]
//           [--check-from K] [--qualify FILE] [--mismatch-log N]
// --qualify: lines "bit q1 q2 ..." (MSB-first output indices): the bit is compared
// only when q1, q2, ... are all 1 in the recorded RTL outputs (valid/enable).
//
// Stimulus lines: "L C|I|O port width" header (I/O concatenated MSB first),
// then "I cycle hex" / "O cycle hex" when the ports change, optional window
// markers "W cycle B" / "W cycle E", and "E cycle" at the end.  Values seen at
// the rising edge of cycle k are applied while the clock is low in cycle k.
// Without window markers one window [--begin, E) is measured
// (out-dir/window.saif); with markers, windows are numbered in order and the
// selected ones are written as out-dir/window-<n>.saif.  --stop ends the
// replay once the last selected window has closed.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

struct Fn { int n = -1; int in[6]; uint64_t tt = 0; };
struct Element { int kind; int out; Fn f, en; int level; };   // kind 0 comb, 2 latch
struct Flop { int clk, pol, iq, group; Fn ns, clr, pre; };
struct Macro {
  int dw, aw, nwm, clk0, csb0, clk1, csb1;
  std::vector<int> addr0, wmask0, din0, addr1, dout1;
  int csb0_r = 1, csb1_r = 1; uint32_t addr0_r = 0, addr1_r = 0; std::vector<uint8_t> wmask0_r, din0_r, mem;
  uint64_t reads = 0, writes = 0;   // accesses performed (whole run)
};
struct Group { int pol; std::vector<int> dirty; };

static std::vector<uint8_t> val;
static std::vector<uint64_t> tc, t1, last_t;
static std::vector<uint32_t> changed_epoch;
static std::vector<Element> elems;
static std::vector<Flop> flops;
static std::vector<Macro> macros;
static std::vector<Group> groups;
static std::vector<uint8_t> flop_dirty;
static std::vector<int> fan_off, fan, clk_off, clk_fan, async_off, async_fan, ffan_off, ffan;
static std::vector<std::vector<int>> bucket;
static std::vector<uint8_t> queued;
static std::vector<int> clock_events, async_events;
static std::vector<uint8_t> clock_event_mark, async_event_mark;
static uint32_t epoch = 1;
static uint64_t now = 0, races = 0, conflicts = 0;

static inline int eval(const Fn &f) {
  unsigned idx = 0;
  for (int i = 0; i < f.n; ++i) idx |= unsigned(val[f.in[i]]) << i;
  return int((f.tt >> idx) & 1u);
}

static inline void mark_flop(int f) {
  if (!flop_dirty[f]) { flop_dirty[f] = 1; groups[flops[f].group].dirty.push_back(f); }
}

static inline void set_net(int net, int v) {
  if (val[net] == v) return;
  if (val[net]) t1[net] += now - last_t[net];
  last_t[net] = now;
  ++tc[net];
  val[net] = uint8_t(v);
  changed_epoch[net] = epoch;
  for (int i = fan_off[net]; i < fan_off[net + 1]; ++i) {
    int e = fan[i];
    if (!queued[e]) { queued[e] = 1; bucket[elems[e].level].push_back(e); }
  }
  for (int i = ffan_off[net]; i < ffan_off[net + 1]; ++i) mark_flop(ffan[i]);
  if (clk_off[net] != clk_off[net + 1] && !clock_event_mark[net]) { clock_event_mark[net] = 1; clock_events.push_back(net); }
  if (async_off[net] != async_off[net + 1] && !async_event_mark[net]) { async_event_mark[net] = 1; async_events.push_back(net); }
}

static void propagate() {
  for (size_t level = 0; level < bucket.size(); ++level) {
    auto &b = bucket[level];
    for (size_t i = 0; i < b.size(); ++i) {
      Element &e = elems[b[i]];
      queued[b[i]] = 0;
      if (e.kind == 0) set_net(e.out, eval(e.f));
      else if (eval(e.en)) set_net(e.out, eval(e.f));
    }
    b.clear();
  }
}

static uint32_t bits_value(const std::vector<int> &nets) {
  uint32_t v = 0;
  for (size_t i = 0; i < nets.size(); ++i) v |= uint32_t(val[nets[i]]) << i;
  return v;
}

// Resolve clock edges (flops, macro ports) and asynchronous controls until stable.
// A flop whose next-state inputs have not changed since it last captured keeps
// its value on a clock edge, so only flops marked dirty are evaluated.
static void settle() {
  propagate();
  for (int guard = 0; guard < 64; ++guard) {
    std::vector<std::pair<int, int>> updates, dout_updates;
    std::vector<std::pair<int, int>> mfire;  // macro, event (0 pos clk0, 1 pos clk1, 2 neg clk0, 3 neg clk1)
    bool any = false;
    for (int net : clock_events) {
      clock_event_mark[net] = 0;
      for (int i = clk_off[net]; i < clk_off[net + 1]; ++i) {
        int code = clk_fan[i];
        if (code >= 0) {
          Group &g = groups[code];
          if ((g.pol == 1) != (val[net] == 1)) continue;
          any = true;
          for (int f : g.dirty) {
            const Flop &fl = flops[f];
            flop_dirty[f] = 0;
            for (int k = 0; k < fl.ns.n; ++k) if (fl.ns.in[k] != fl.iq && changed_epoch[fl.ns.in[k]] == epoch) ++races;
            int v = eval(fl.ns);
            if (fl.clr.n >= 0 && eval(fl.clr)) v = 0;
            else if (fl.pre.n >= 0 && eval(fl.pre)) v = 1;
            updates.push_back({fl.iq, v});
          }
          g.dirty.clear();
        } else {
          int m = (-code - 1) >> 1, port = (-code - 1) & 1;
          mfire.push_back({m, (val[net] ? 0 : 2) + port});
          any = true;
        }
      }
    }
    clock_events.clear();
    for (int net : async_events) {
      async_event_mark[net] = 0;
      for (int i = async_off[net]; i < async_off[net + 1]; ++i) {
        const Flop &f = flops[async_fan[i]];
        bool c = f.clr.n >= 0 && eval(f.clr), p = f.pre.n >= 0 && eval(f.pre);
        if (c) updates.push_back({f.iq, 0}); else if (p) updates.push_back({f.iq, 1});
        any = true;
      }
    }
    async_events.clear();
    if (!any) return;
    // OpenRAM model: posedge registers the port inputs; negedge performs the
    // write of port 0 and then the read of port 1.
    for (auto [mi, ev] : mfire) {
      Macro &m = macros[mi];
      if (ev == 0) {
        m.csb0_r = val[m.csb0]; m.addr0_r = bits_value(m.addr0);
        for (int i = 0; i < m.nwm; ++i) m.wmask0_r[i] = m.wmask0.empty() ? 1 : val[m.wmask0[i]];
        for (int i = 0; i < m.dw; ++i) m.din0_r[i] = val[m.din0[i]];
      } else if (ev == 1) {
        m.csb1_r = val[m.csb1]; m.addr1_r = bits_value(m.addr1);
        if (!val[m.csb0] && !val[m.csb1] && bits_value(m.addr0) == bits_value(m.addr1)) ++conflicts;
      }
    }
    for (auto [mi, ev] : mfire) {
      Macro &m = macros[mi];
      if (ev == 2 && !m.csb0_r) {
        ++m.writes;
        int slice = m.dw / m.nwm;
        for (int i = 0; i < m.dw; ++i) if (m.wmask0_r[i / slice]) m.mem[size_t(m.addr0_r) * m.dw + i] = m.din0_r[i];
      }
    }
    for (auto [mi, ev] : mfire) {
      Macro &m = macros[mi];
      if (ev == 3 && !m.csb1_r) {
        ++m.reads;
        for (int i = 0; i < m.dw; ++i) dout_updates.push_back({m.dout1[i], m.mem[size_t(m.addr1_r) * m.dw + i]});
      }
    }
    ++epoch;
    for (auto [n, v] : updates) set_net(n, v);
    for (auto [n, v] : dout_updates) set_net(n, v);
    propagate();
  }
  std::fprintf(stderr, "clock/async resolution did not converge\n");
  std::exit(3);
}

static std::vector<int> read_ints(std::istringstream &s, int n) {
  std::vector<int> v(n);
  for (auto &x : v) s >> x;
  return v;
}

static Fn read_fn(std::istringstream &s) {
  Fn f; s >> f.n;
  if (f.n >= 0) { for (int i = 0; i < f.n; ++i) s >> f.in[i]; std::string h; s >> h; f.tt = std::stoull(h, nullptr, 16); }
  return f;
}

struct Window {
  long index, begin, end = -1, checked = 0, mismatched = 0;
  std::vector<uint64_t> base_reads, base_writes, reads, writes;
  bool saved = false;
  std::vector<uint64_t> base_tc, base_t1;
  uint64_t toggles = 0;
};

static inline uint64_t high_time(int n) { return t1[n] + (val[n] ? now - last_t[n] : 0); }

int main(int argc, char **argv) {
  if (argc < 5) { std::fprintf(stderr, "usage: gatesim program saifmap stimulus out-dir [--begin N] [--windows i,j] [--stop]\n"); return 2; }
  long begin_cycle = 0;
  bool stop = false, markers = false;
  long mismatch_log = 0, check_from = 0;
  std::string qualify_path;
  FILE *mlog = nullptr;
  std::set<long> selected;
  for (int i = 5; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--begin" && i + 1 < argc) begin_cycle = std::atol(argv[++i]);
    else if (a == "--stop") stop = true;
    else if (a == "--mismatch-log" && i + 1 < argc) mismatch_log = std::atol(argv[++i]);
    else if (a == "--check-from" && i + 1 < argc) check_from = std::atol(argv[++i]);
    else if (a == "--qualify" && i + 1 < argc) qualify_path = argv[++i];
    else if (a == "--windows" && i + 1 < argc) {
      markers = true; std::stringstream s(argv[++i]); std::string item;
      while (std::getline(s, item, ',')) selected.insert(std::atol(item.c_str()));
    } else { std::fprintf(stderr, "unknown option %s\n", a.c_str()); return 2; }
  }
  std::string out_dir = argv[4];
  std::ifstream prog(argv[1]);
  std::string line, tag;
  int nets = 0, const0 = -1, const1 = -1;
  std::unordered_map<std::string, std::vector<int>> ports;  // name -> nets lsb first
  std::vector<std::vector<int>> fan_lists, clk_lists, async_lists, ffan_lists;
  std::map<std::pair<int, int>, int> group_of;
  while (std::getline(prog, line)) {
    std::istringstream s(line); s >> tag;
    if (tag == "NETS") {
      s >> nets >> const0 >> const1;
      fan_lists.resize(nets); clk_lists.resize(nets); async_lists.resize(nets); ffan_lists.resize(nets);
    } else if (tag == "PORT") { std::string name; int w; s >> name >> w; ports[name] = read_ints(s, w); }
    else if (tag == "C" || tag == "L") {
      Element e; e.kind = tag == "C" ? 0 : 2; s >> e.out >> e.level;
      if (e.kind == 2) e.en = read_fn(s);
      e.f = read_fn(s);
      int idx = int(elems.size());
      for (int i = 0; i < e.f.n; ++i) fan_lists[e.f.in[i]].push_back(idx);
      if (e.kind == 2) for (int i = 0; i < e.en.n; ++i) fan_lists[e.en.in[i]].push_back(idx);
      elems.push_back(e);
    } else if (tag == "F") {
      Flop f; s >> f.clk >> f.pol >> f.iq; f.ns = read_fn(s); f.clr = read_fn(s); f.pre = read_fn(s);
      int idx = int(flops.size());
      auto key = std::make_pair(f.clk, f.pol);
      auto it = group_of.find(key);
      if (it == group_of.end()) {
        it = group_of.emplace(key, int(groups.size())).first;
        groups.push_back(Group{f.pol, {}});
        clk_lists[f.clk].push_back(it->second);
      }
      f.group = it->second;
      for (int i = 0; i < f.ns.n; ++i) ffan_lists[f.ns.in[i]].push_back(idx);
      for (const Fn *a : {&f.clr, &f.pre}) for (int i = 0; i < a->n; ++i) async_lists[a->in[i]].push_back(idx);
      flops.push_back(f);
    } else if (tag == "M") {
      Macro m; s >> m.dw >> m.aw >> m.nwm >> m.clk0 >> m.csb0 >> m.clk1 >> m.csb1;
      m.addr0 = read_ints(s, m.aw); int wm; s >> wm; m.wmask0 = read_ints(s, wm); m.din0 = read_ints(s, m.dw);
      m.addr1 = read_ints(s, m.aw); m.dout1 = read_ints(s, m.dw);
      m.wmask0_r.assign(m.nwm, 0); m.din0_r.assign(m.dw, 0); m.mem.assign(size_t(m.dw) << m.aw, 0);
      int idx = int(macros.size());
      clk_lists[m.clk0].push_back(-(2 * idx + 0) - 1);
      clk_lists[m.clk1].push_back(-(2 * idx + 1) - 1);
      macros.push_back(std::move(m));
    }
  }
  auto csr = [](std::vector<std::vector<int>> &lists, std::vector<int> &off, std::vector<int> &flat) {
    off.assign(lists.size() + 1, 0);
    for (size_t i = 0; i < lists.size(); ++i) off[i + 1] = off[i] + int(lists[i].size());
    flat.reserve(off.back());
    for (auto &l : lists) { flat.insert(flat.end(), l.begin(), l.end()); std::vector<int>().swap(l); }
  };
  csr(fan_lists, fan_off, fan); csr(clk_lists, clk_off, clk_fan); csr(async_lists, async_off, async_fan); csr(ffan_lists, ffan_off, ffan);
  int max_level = 0;
  for (auto &e : elems) max_level = std::max(max_level, e.level);
  bucket.assign(max_level + 1, {});
  val.assign(nets, 0); tc.assign(nets, 0); t1.assign(nets, 0); last_t.assign(nets, 0); changed_epoch.assign(nets, 0);
  clock_event_mark.assign(nets, 0); async_event_mark.assign(nets, 0); queued.assign(elems.size(), 0);
  flop_dirty.assign(flops.size(), 0);
  for (size_t f = 0; f < flops.size(); ++f) mark_flop(int(f));
  if (const1 >= 0) val[const1] = 1;
  // Initial settle: every element evaluated once from the all-zero state.
  for (size_t i = 0; i < elems.size(); ++i) { queued[i] = 1; bucket[elems[i].level].push_back(int(i)); }
  propagate();
  clock_events.clear(); async_events.clear(); std::fill(clock_event_mark.begin(), clock_event_mark.end(), 0);
  std::fill(async_event_mark.begin(), async_event_mark.end(), 0);

  // SAIF instance map (kept in memory: name lines and pin -> net)
  std::vector<std::string> map_lines;
  {
    std::ifstream map(argv[2]);
    while (std::getline(map, line)) map_lines.push_back(line);
  }
  long saif_instances = 0, saif_pins = 0;
  auto write_saif = [&](const std::string &path, Window &w) {
    uint64_t duration = uint64_t(w.end - w.begin) * 10000;
    FILE *out = std::fopen(path.c_str(), "w");
    std::fprintf(out, "(SAIFILE\n(SAIFVERSION \"2.0\")\n(DIRECTION \"backward\")\n(PROGRAM_NAME \"student-mini-gatesim\")\n"
                 "(DIVIDER / )\n(TIMESCALE 1ps)\n(DURATION %llu)\n (INSTANCE TOP\n  (INSTANCE %s\n",
                 (unsigned long long)duration, map_lines[0].c_str());
    auto net_line = [&](const char *name, size_t len, int n) {
      uint64_t hi = high_time(n) - w.base_t1[n];
      if (hi > duration) hi = duration;
      std::fprintf(out, "     (%.*s (T0 %llu) (T1 %llu) (TZ 0) (TX 0) (TB 0) (TC %llu))\n", int(len), name,
                   (unsigned long long)(duration - hi), (unsigned long long)hi, (unsigned long long)(tc[n] - w.base_tc[n]));
    };
    bool open_inst = false, open_ports = false;
    saif_instances = saif_pins = 0;
    for (size_t i = 1; i < map_lines.size(); ++i) {
      const std::string &l = map_lines[i];
      if (l.empty()) continue;
      if (l[0] == 'I' || l[0] == 'D' || l[0] == 'X') {
        if (open_ports) { std::fprintf(out, "   )\n"); open_ports = false; }
        if (open_inst) { std::fprintf(out, "    )\n   )\n"); open_inst = false; }
        if (l[0] == 'I') { std::fprintf(out, "   (INSTANCE %s\n    (NET\n", l.c_str() + 2); open_inst = true; ++saif_instances; }
        else if (l[0] == 'D') std::fprintf(out, "  (INSTANCE %s\n", l.c_str() + 2);   // hard-block scope
        else std::fprintf(out, "  )\n");
      } else if (l[0] == 'P' || l[0] == 'T') {
        if (l[0] == 'T' && !open_ports) { std::fprintf(out, "   (NET\n"); open_ports = true; }
        size_t sp = l.rfind(' ');
        net_line(l.c_str() + 2, sp - 2, std::atoi(l.c_str() + sp + 1));
        if (l[0] == 'P') ++saif_pins;
      }
    }
    if (open_ports) std::fprintf(out, "   )\n");
    if (open_inst) std::fprintf(out, "    )\n   )\n");
    std::fprintf(out, "  )\n )\n)\n");
    std::fclose(out);
    uint64_t toggles = 0;
    for (int n = 0; n < nets; ++n) toggles += tc[n] - w.base_tc[n];
    w.toggles = toggles;
    w.saved = true;
    for (size_t i = 0; i < macros.size(); ++i) { w.reads.push_back(macros[i].reads - w.base_reads[i]); w.writes.push_back(macros[i].writes - w.base_writes[i]); }
  };
  auto open_window = [&](long index, long cycle) {
    Window w; w.index = index; w.begin = cycle;
    for (auto &m : macros) { w.base_reads.push_back(m.reads); w.base_writes.push_back(m.writes); }
    w.base_tc = tc; w.base_t1.resize(nets);
    for (int n = 0; n < nets; ++n) w.base_t1[n] = high_time(n);
    return w;
  };

  std::ifstream stim(argv[3]);
  std::vector<int> in_nets, out_nets;  // MSB first
  std::vector<std::vector<int>> qualify;  // output bit -> qualifying output bits
  if (!qualify_path.empty()) {
    std::ifstream q(qualify_path);
    std::string ql;
    while (std::getline(q, ql)) {
      std::istringstream s(ql); long bit; s >> bit;
      if (bit < 0) continue;
      if (size_t(bit) >= qualify.size()) qualify.resize(bit + 1);
      int qb; while (s >> qb) qualify[bit].push_back(qb);
    }
  }
  int clock_net = -1;
  long cycles = 0, checked = 0, mismatched = 0, first_mismatch = -1, end_cycle = -1, window_count = 0;
  std::string first_detail;
  auto expand = [&](const std::string &port, int w, std::vector<int> &dst) {
    auto it = ports.find(port);
    if (it == ports.end() || int(it->second.size()) != w) { std::fprintf(stderr, "port %s width %d not in netlist\n", port.c_str(), w); std::exit(4); }
    for (int i = w - 1; i >= 0; --i) dst.push_back(it->second[i]);
  };
  auto hex_bits = [](const std::string &hex, size_t width) {
    std::vector<uint8_t> bits(width, 0);   // MSB first
    size_t pos = width;
    for (size_t i = hex.size(); i-- > 0 && pos > 0;) {
      char c = hex[i]; int d = (c >= '0' && c <= '9') ? c - '0' : (c | 32) - 'a' + 10;
      if (c == 'x' || c == 'X' || c == 'z' || c == 'Z') d = 0;
      for (int b = 0; b < 4 && pos > 0; ++b) bits[--pos] = uint8_t((d >> b) & 1);
    }
    return bits;
  };
  std::vector<uint8_t> cur_out, inputs_now;
  std::vector<Window> done;
  Window *active = nullptr;
  Window current;
  if (!markers) { now = uint64_t(begin_cycle) * 10000; }
  auto run_cycle = [&](long k) {
    if (!markers && k == begin_cycle) { now = uint64_t(k) * 10000; current = open_window(0, k); active = &current; }
    now = uint64_t(k) * 10000; ++epoch;
    set_net(clock_net, 0);
    if (!inputs_now.empty()) for (size_t i = 0; i < in_nets.size(); ++i) set_net(in_nets[i], inputs_now[i]);
    settle();
    if (!cur_out.empty() && k >= check_from) {
      // A bit is compared only when all of its qualifying output bits (e.g.
      // valid, write, byte enable) are 1 in the recorded RTL value.
      auto differs = [&](size_t i) {
        if (val[out_nets[i]] == cur_out[i]) return false;
        if (i < qualify.size()) for (int q : qualify[i]) if (!cur_out[q]) return false;
        return true;
      };
      ++checked; bool bad = false;
      for (size_t i = 0; i < out_nets.size(); ++i) if (differs(i)) { bad = true; break; }
      if (active) { ++active->checked; if (bad) ++active->mismatched; }
      if (bad) {
        ++mismatched;
        if (mismatch_log > 0) {
          if (!mlog) mlog = std::fopen((out_dir + "/mismatch.log").c_str(), "w");
          --mismatch_log;
          std::fprintf(mlog, "%ld", k);
          for (size_t i = 0; i < out_nets.size(); ++i) if (differs(i)) std::fprintf(mlog, " %zu:%d", i, int(cur_out[i]));
          std::fputc('\n', mlog);
        }
        if (first_mismatch < 0) {
          first_mismatch = k;
          std::ostringstream d;
          for (size_t i = 0; i < out_nets.size(); ++i) if (differs(i)) d << i << ' ';
          first_detail = d.str().substr(0, 400);
        }
      }
    }
    now = uint64_t(k) * 10000 + 5000; ++epoch;
    set_net(clock_net, 1);
    settle();
    ++cycles;
  };
  long cursor = 0, last_selected = selected.empty() ? -1 : *selected.rbegin();
  bool stopped = false;
  while (std::getline(stim, line)) {
    if (line.empty()) continue;
    std::istringstream s(line); s >> tag;
    if (tag == "L") {
      std::string dir, port; int w; s >> dir >> port >> w;
      if (dir == "I") expand(port, w, in_nets); else if (dir == "O") expand(port, w, out_nets); else if (dir == "C") clock_net = ports.at(port)[0];
      continue;
    }
    long k; s >> k;
    while (cursor < k) run_cycle(cursor++);
    if (tag == "I") { std::string h; s >> h; inputs_now = hex_bits(h, in_nets.size()); }
    else if (tag == "O") { std::string h; s >> h; cur_out = hex_bits(h, out_nets.size()); }
    else if (tag == "W" && markers) {
      std::string what; s >> what;
      now = uint64_t(k) * 10000;
      if (what == "B") {
        if (selected.count(window_count)) { current = open_window(window_count, k); active = &current; }
        ++window_count;
      } else if (what == "E" && active) {
        active->end = k;
        write_saif(out_dir + "/window-" + std::to_string(active->index) + ".saif", *active);
        Window keep = *active; keep.base_tc.clear(); keep.base_t1.clear(); keep.base_tc.shrink_to_fit(); keep.base_t1.shrink_to_fit();
        done.push_back(std::move(keep)); active = nullptr;
        if (stop && done.back().index == last_selected) { stopped = true; end_cycle = k; break; }
      }
    } else if (tag == "E") { end_cycle = k; break; }
  }
  if (end_cycle < 0) { std::fprintf(stderr, "stimulus has no end record\n"); return 5; }
  now = uint64_t(end_cycle) * 10000;
  if (!markers) {
    if (!active) { std::fprintf(stderr, "window begin %ld beyond the end %ld\n", begin_cycle, end_cycle); return 6; }
    active->end = end_cycle;
    write_saif(out_dir + "/window.saif", *active);
    done.push_back(*active);
  }
  if (markers && done.size() != selected.size()) { std::fprintf(stderr, "only %zu of %zu selected windows closed\n", done.size(), selected.size()); return 7; }
  FILE *rep = std::fopen((out_dir + "/gatesim.json").c_str(), "w");
  std::fprintf(rep, "{\"cycles\": %ld, \"end_cycle\": %ld, \"stopped_after_last_window\": %s, \"checked_cycles\": %ld, "
               "\"mismatched_cycles\": %ld, \"first_mismatch_cycle\": %ld, \"first_mismatch_bits\": \"%s\", \"races\": %llu, "
               "\"macro_read_write_conflicts\": %llu, \"nets\": %d, \"elements\": %zu, \"flops\": %zu, \"macros\": %zu, "
               "\"saif_instances\": %ld, \"saif_pins\": %ld, \"windows_seen\": %ld, \"windows\": [",
               cycles, end_cycle, stopped ? "true" : "false", checked, mismatched, first_mismatch, first_detail.c_str(),
               (unsigned long long)races, (unsigned long long)conflicts, nets, elems.size(), flops.size(), macros.size(),
               saif_instances, saif_pins, markers ? window_count : 1);
  for (size_t i = 0; i < done.size(); ++i) {
    std::fprintf(rep, "%s{\"index\": %ld, \"begin_cycle\": %ld, \"end_cycle\": %ld, \"duration_ps\": %llu, \"checked_cycles\": %ld, "
                 "\"mismatched_cycles\": %ld, \"total_toggles\": %llu, \"macro_reads\": [", i ? ", " : "", done[i].index, done[i].begin, done[i].end,
                 (unsigned long long)(uint64_t(done[i].end - done[i].begin) * 10000), done[i].checked, done[i].mismatched,
                 (unsigned long long)done[i].toggles);
    for (size_t j = 0; j < done[i].reads.size(); ++j) std::fprintf(rep, "%s%llu", j ? ", " : "", (unsigned long long)done[i].reads[j]);
    std::fprintf(rep, "], \"macro_writes\": [");
    for (size_t j = 0; j < done[i].writes.size(); ++j) std::fprintf(rep, "%s%llu", j ? ", " : "", (unsigned long long)done[i].writes[j]);
    std::fprintf(rep, "]}");
  }
  std::fprintf(rep, "]}\n");
  std::fclose(rep);
  if (mlog) std::fclose(mlog);
  std::printf("cycles=%ld checked=%ld mismatched=%ld races=%llu windows=%zu\n", cycles, checked, mismatched,
              (unsigned long long)races, done.size());
  return mismatched ? 1 : 0;
}
