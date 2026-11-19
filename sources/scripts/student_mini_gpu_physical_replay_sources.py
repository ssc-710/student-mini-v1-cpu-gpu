"""Checked, isolated source derivations for full GPU physical-boundary replay."""
import re


TOKEN=re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\\[^\s]+|[A-Za-z_$][A-Za-z0-9_$]*')


def overlay_configure(source):
    anchor='find "$source_dir" -type d -path "$source_pattern"'
    if source.count(anchor)!=1:raise ValueError('unknown upstream configure traversal')
    return source.replace(anchor,'find -L "$source_dir" -type d -path "$source_pattern"')


def rename_modules(source,mapping=None):
    if mapping is None:
        names=re.findall(r'(?m)^module\s+([A-Za-z_$][A-Za-z0-9_$]*)\b',source)
        if not names or len(names)!=len(set(names)) or 'Vortex' not in names:
            raise ValueError('ambiguous mapped core modules')
        mapping={name:'mini_physical_'+name for name in names}
    def rename(match):
        token=match.group()
        return mapping.get(token,token)
    return TOKEN.sub(rename,source),mapping


def connect_shim(source):
    changed,count=re.subn(r'\bVortex\s+vortex\s*\(', 'student_mini_gpu_physical_bridge vortex (',source)
    if count!=1:raise ValueError('ambiguous simulator core instance')
    return changed


def timing_processor(source):
    pattern=r'  void eval\(\) \{[\s\S]*?\n  \}\n\n  void mem_bus_reset\(\)'
    replacement='''  void eval() {
    // Explicit 1 ps context units: 5,000 ps per half-cycle = 100 MHz.
    // Drain every real OpenRAM delay event, never suppress model delays.
    const uint64_t boundary = context_->time() + 5000;
    auto evaluate = [&]() {
      device_->eval();
    #ifdef VCD_OUTPUT
      if (sim_trace_enabled()) tfp_->dump(context_->time());
    #endif
    #ifdef SAIF_OUTPUT
      if (sim_trace_enabled()) sfp_->dump(context_->time());
    #endif
    };
    evaluate();
    while (device_->eventsPending() && device_->nextTimeSlot() < boundary) {
      context_->time(device_->nextTimeSlot());
      evaluate();
    }
    context_->time(boundary);
    ++timestamp;
  }

  void mem_bus_reset()'''
    original=re.findall(pattern,source)
    if len(original)!=1 or original[0].count('++timestamp;')!=1 or 'device_->eval();' not in original[0]:
        raise ValueError('unknown simulator time-step implementation')
    return re.sub(pattern,lambda _:replacement,source)


def quiet_macro(source):
    changed,count=re.subn(r'parameter VERBOSE\s*=\s*1\s*;', 'parameter VERBOSE = 0 ;',source)
    if count!=1:raise ValueError('unexpected OpenRAM verbosity parameter')
    return changed
