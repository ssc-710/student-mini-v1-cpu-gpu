"""Source derivations for the GPU protocol qualification runs (MINI-31/32/33).

The host model (Vortex rtlsim processor.cpp) gains:
  * student_mini_protocol_param(): the per-run protocol parameters from
    STUDENT_MINI_PROTOCOL="prob256,seed,hold,reset_after" (DPI for the bridge);
  * a log of every DCR write since construction;
  * reset-recovery: during the first kernel launch, after `reset_after` busy
    cycles, the device is reset (same reset sequence as power-on), every logged
    DCR write is replayed and the launch is reissued; the host then waits for
    that reissued launch exactly like any other.
"""
import re

PARAM = '''
// student-mini protocol qualification parameters (MINI-31/32/33).
extern "C" int student_mini_protocol_param(int which) {
  const char* text = std::getenv("STUDENT_MINI_PROTOCOL");
  int fields[4] = {0, 0, 0, 0};
  if (text) std::sscanf(text, "%d,%d,%d,%d", &fields[0], &fields[1], &fields[2], &fields[3]);
  return (which >= 0 && which < 4) ? fields[which] : 0;
}
// Outstanding host commands (queued in the bridge + accepted but not yet answered).
// The original host is synchronous; with held responses it waits for zero after
// each command so that `busy` (core or command adapter) keeps its meaning.
static int student_pending_commands = 0;
extern "C" void student_mini_protocol_pending(int outstanding) { student_pending_commands = outstanding; }
// The bridge hands its cumulative protocol counters over through this call (it
// stores integers only); the host prints them after every launch's status read.
static int student_protocol_values[10];
static int student_protocol_reports = 0;
extern "C" void student_mini_protocol_report(int a0, int a1, int a2, int a3, int a4, int a5, int a6, int a7, int a8, int a9) {
  int v[10] = {a0, a1, a2, a3, a4, a5, a6, a7, a8, a9};
  for (int i = 0; i < 10; ++i) student_protocol_values[i] = v[i];
  ++student_protocol_reports;
}
static void student_mini_protocol_print() {
  const int *v = student_protocol_values;
  std::cout << "STUDENT_GPU_PROTOCOL_PART bp_prob=" << v[0] << " bp_seed=" << v[1] << " hold=" << v[2] << std::endl;
  std::cout << "STUDENT_GPU_PROTOCOL_PART stalled_req_cycles=" << v[3] << " stalled_rsp_cycles=" << v[4] << std::endl;
  std::cout << "STUDENT_GPU_PROTOCOL_PART held_rsp_cycles=" << v[5] << " stability_violations=" << v[6] << std::endl;
  std::cout << "STUDENT_GPU_PROTOCOL_PART commands=" << v[7] << " responses=" << v[8] << " fifo_peak=" << v[9] << std::endl;
  std::cout << "STUDENT_GPU_PROTOCOL_END reports=" << student_protocol_reports << std::endl;
}
'''

EVENT = re.compile(r'^STUDENT_GPU_PROTOCOL_PART (.*)$')
RESET = re.compile(r'^STUDENT_GPU_PROTOCOL_RESET busy_cycles=(\d+) busy=([01])$')
REISSUE = re.compile(r'^STUDENT_GPU_PROTOCOL_REISSUED dcr_writes=(\d+) busy=([01])$')


def protocol_processor(source):
    edits = [
        ('#include <util.h>\n', '#include <util.h>\n#include <cstdio>\n' + PARAM),
        ('              << " busy=" << ((student_status >> 1) & 1u) << std::endl;\n',
         '              << " busy=" << ((student_status >> 1) & 1u) << std::endl;\n    student_mini_protocol_print();\n'),
        ('  int dcr_write(uint32_t addr, uint32_t value) {\n',
         '  int dcr_write(uint32_t addr, uint32_t value) {\n    student_dcr_log_.emplace_back(addr, value);\n'
         '    if (std::getenv("STUDENT_MINI_DEBUG")) std::cout << "DBG W " << std::hex << addr << " " << value << std::dec\n'
         '                                                  << " busy=" << int(device_->busy) << std::endl;\n'),
        ('    *value = device_->dcr_rsp_data;\n',
         '    *value = device_->dcr_rsp_data;\n'
         '    if (std::getenv("STUDENT_MINI_DEBUG")) std::cout << "DBG R " << std::hex << addr << " " << *value << std::dec\n'
         '                                                  << " busy=" << int(device_->busy) << std::endl;\n'),
        ('    device_->start = 1;\n    this->tick();\n    device_->start = 0;\n',
         '    if (std::getenv("STUDENT_MINI_DEBUG")) std::cout << "DBG START busy=" << int(device_->busy) << std::endl;\n'
         '    device_->start = 1;\n    this->tick();\n    device_->start = 0;\n'
         '    while (student_pending_commands > 0) this->tick();   // start accepted and answered\n'),
        ('    device_->dcr_req_valid = 0;\n    this->tick();\n    return 0;\n',
         '    device_->dcr_req_valid = 0;\n    this->tick();\n'
         '    while (student_pending_commands > 0) this->tick();   // write accepted and answered\n    return 0;\n'),
        ('    if (cout_drainer) cout_drainer->tick(); // final flush\n',
         '    if (std::getenv("STUDENT_MINI_DEBUG")) std::cout << "DBG END busy=" << int(device_->busy) << std::endl;\n'
         '    if (cout_drainer) cout_drainer->tick(); // final flush\n'),
        ('  std::unordered_map<int, std::stringstream> print_bufs_;\n',
         '  std::unordered_map<int, std::stringstream> print_bufs_;\n'
         '  std::vector<std::pair<uint32_t, uint32_t>> student_dcr_log_;\n  int student_reset_done_ = 0;\n'),
        ('    while (device_->busy) {\n      this->tick();\n',
         '    uint64_t student_busy_cycles = 0;\n'
         '    while (device_->busy) {\n      this->tick();\n'
         '      if (student_mini_protocol_param(3) > 0 && !student_reset_done_\n'
         '          && ++student_busy_cycles == uint64_t(student_mini_protocol_param(3))) {\n'
         '        student_reset_done_ = 1;\n'
         '        std::cout << "STUDENT_GPU_PROTOCOL_RESET busy_cycles=" << student_busy_cycles\n'
         '                  << " busy=" << int(device_->busy) << std::endl;\n'
         '        auto replay = student_dcr_log_;\n'
         '        this->reset();\n'
         '        for (auto& w : replay) this->dcr_write(w.first, w.second);\n'
         '        student_dcr_log_ = replay;\n'
         '        device_->start = 1;\n        this->tick();\n        device_->start = 0;\n'
         '        while (student_pending_commands > 0) this->tick();\n'
         '        for (uint32_t i = 0; !device_->busy && i < NO_WORK_TIMEOUT; ++i) this->tick();\n'
         '        std::cout << "STUDENT_GPU_PROTOCOL_REISSUED dcr_writes=" << replay.size()\n'
         '                  << " busy=" << int(device_->busy) << std::endl;\n'
         '      }\n'),
    ]
    for old, new in edits:
        if source.count(old) != 1:
            raise ValueError('rtlsim protocol seam changed: ' + old.strip()[:50])
        source = source.replace(old, new)
    return source


def protocol_env(vector):
    p = vector['inputs']['protocol']
    prob = int(round(float(p['backpressure_probability']) * 256))
    return f"{prob},{int(p['backpressure_seed'])},{int(p['response_hold_cycles'])},{64 if p['reset_and_reissue'] else 0}"


def protocol_events(text):
    lines = text.splitlines()
    frames, current = [], []
    for line in lines:
        m = EVENT.match(line)
        if m:
            current.append(dict(kv.split('=', 1) for kv in m.group(1).split()))
        elif line.startswith('STUDENT_GPU_PROTOCOL_END'):
            frames.append(current)
            current = []
    resets = [m.groups() for m in map(RESET.match, lines) if m]
    reissues = [m.groups() for m in map(REISSUE.match, lines) if m]
    if not frames or len(frames[-1]) != 4:
        return dict(complete=False)
    value = {k: int(v) for part in frames[-1] for k, v in part.items()}
    value['frames'] = len(frames)
    value.update(complete=True, resets=[dict(busy_cycles=int(c), busy_at_reset=int(b)) for c, b in resets],
                 reissues=[dict(dcr_writes=int(n), busy_after_start=int(b)) for n, b in reissues])
    return value


def silent_macro(source):
    """Drop the OpenRAM model's same-address read/write notice ($display).

    The runtime keeps ticking the model while it tears down at process exit
    (performance dump after C++ static destructors ran); any $display then
    corrupts the heap.  The notice is informational only.
    """
    changed, count = re.subn(r'\$display\(\$time," WARNING: Writing and reading [^;]*\);', ';', source)
    if count != 1:
        raise ValueError('unexpected OpenRAM simultaneous-access notice')
    return changed
