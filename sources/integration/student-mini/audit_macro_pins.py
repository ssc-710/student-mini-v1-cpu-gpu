# Read-only physical check of hard-macro signal pins in a routed database (openroad -python).
# A macro signal pin on a net with two or more terminals counts as accessed and routed only when a
# wire segment or via of that same net overlaps one of the pin's shapes on the same metal layer
# (instance-transformed pin geometry; a via counts on its bottom and top metal).  A pin whose net has
# no other terminal (an output without loads) needs no wire and is reported as floating.
# DRT keeps macro access points per unique-instance pattern on the master, so the per-instance
# preferred-access-point list is empty for macros and is not a usable access test.
import os

import odb
from openroad import Design, Tech

tech = Tech()  # must outlive the design (a temporary Tech crashes readDb)
design = Design(tech)
design.readDb(os.environ['STUDENT_MINI_ROUTE_ODB'])
block = design.getBlock()


def wire_boxes(wire):
    out = []
    itr = odb.dbWirePathItr()
    itr.begin(wire)
    path = odb.dbWirePath()
    while itr.getNextPath(path):
        ps = odb.dbWirePathShape()
        while itr.getNextShape(ps):
            shape = ps.shape
            if shape.isVia():
                via = shape.getTechVia() or shape.getVia()
                names = (via.getBottomLayer().getName(), via.getTopLayer().getName())
            else:
                names = (shape.getTechLayer().getName(),)
            for name in names:
                out.append((name, shape.xMin(), shape.yMin(), shape.xMax(), shape.yMax()))
    return out


touched = missing = floating = 0
for inst in block.getInsts():
    if inst.getMaster().getType() != 'BLOCK':
        continue
    for term in inst.getITerms():
        mterm, net = term.getMTerm(), term.getNet()
        if mterm.getSigType() in ('POWER', 'GROUND') or net is None:
            continue
        if len(net.getITerms()) + len(net.getBTerms()) < 2:
            floating += 1
            print(f'PLATFORM_AUDIT_FLOATING_OUTPUT {inst.getName()}/{mterm.getName()}')
            continue
        pins = [(layer.getName(), rect) for layer, rect in term.getGeometries() if layer is not None]
        wire = net.getWire()
        hit = wire is not None and any(
            name == pin and x0 <= r.xMax() and r.xMin() <= x1 and y0 <= r.yMax() and r.yMin() <= y1
            for name, x0, y0, x1, y1 in wire_boxes(wire) for pin, r in pins)
        if hit:
            touched += 1
        else:
            missing += 1
            print(f'PLATFORM_AUDIT_PIN_NOT_REACHED {inst.getName()}/{mterm.getName()}')
print(f'PLATFORM_AUDIT_PINS reached={touched} not_reached={missing} floating={floating}')
print('PLATFORM_AUDIT_PINS_COMPLETE')
