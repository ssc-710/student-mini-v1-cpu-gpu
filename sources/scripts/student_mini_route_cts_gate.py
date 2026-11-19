"""Fail closed between clock-tree synthesis and any routing work."""
from scripts.route_student_mini_platform import nonnegative


def check_cts(metrics):
    return nonnegative(metrics.get('cts__timing__setup__ws'),'100 MHz CTS WNS')


def inject(source):
    needle="                if target == 'do-5_1_grt':"
    if source.count(needle)!=1:raise ValueError('CTS gate insertion seam changed')
    source=source.replace(needle,"""                if target == 'do-4_1_cts':
                    from scripts.student_mini_route_cts_gate import check_cts
                    cts_metrics = json.loads((logs/'4_1_cts.json').read_text())
                    result['cts_wns_ns'] = cts_metrics.get('cts__timing__setup__ws')
                    check_cts(cts_metrics)
"""+needle)
    needle='paths = [Path(__file__),'
    if source.count(needle)!=1:raise ValueError('CTS gate binding seam changed')
    return source.replace(needle,needle+"ROOT/'scripts/student_mini_route_cts_gate.py',")
