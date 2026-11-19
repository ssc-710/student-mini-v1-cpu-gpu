"""Use an anchored executable-line seam, excluding nested producer string literals."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import requeue_student_mini_interrupted as recovery
from scripts.resume_student_mini_interrupted import replace_once


def derive(source,root,marker,required):
    source=replace_once(source,'ROOT = Path(__file__).resolve().parents[1]','ROOT = Path('+repr(str(root))+')')
    before='\n    '+marker+' = [Path(__file__),'
    required=[*required,ROOT/'scripts/requeue_student_mini_interrupted.py']
    return replace_once(source,before,before+''.join(' Path('+repr(str(p))+'),' for p in required))


if __name__=='__main__':
    recovery.derive=derive
    # The controller identity must bind this entry point as well as its library.
    recovery.__file__=__file__
    raise SystemExit(recovery.main())
