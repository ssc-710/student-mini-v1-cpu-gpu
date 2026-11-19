"""Lightweight parser and ABI checks; no target execution or regression PASS."""
import importlib.util
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('gpu_regression',BASE/'tools/run_gpu_regression.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def log(self,token=4):
        return ('P3_HOST_TIMING kernel_sync_seconds=1.0 qa_compute_readback_seconds=2.0\n'
            'STUDENT_NATIVE_GPU status=0 count=1\n'
            f'STUDENT_NATIVE_TOKEN step=0 token={token} hidden='+','.join(['0000']*16)+' logits='+','.join(['0000']*256)+'\n'
            'STUDENT_NATIVE_GPU_COMPLETE count=1 p1=1 p2=0 p3=0\n'
            'PERF: instrs=123, cycles=456\n')

    def test_full_state(self):
        result=runner.parse_log(self.log())
        self.assertEqual(result['token_ids'],[4])
        self.assertEqual(result['tokens_per_kernel_wall_second'],1.0)

    def test_truncated_state_fails(self):
        with self.assertRaises(AssertionError):runner.parse_log(self.log().replace('hidden=0000,','hidden=',1))

    def test_duplicate_completion_fails(self):
        with self.assertRaises(AssertionError):runner.parse_log(self.log()+'STUDENT_NATIVE_GPU_COMPLETE count=1 p1=1 p2=0 p3=0\n')

    def test_missing_eos_before_limit_fails(self):
        with self.assertRaises(AssertionError):runner.parse_log(self.log(17))

    def test_abi_replacement(self):
        source='#define COURSE_NATIVE_IMAGE_BYTES 5\n#ifndef STUDENT_MINI_NATIVE_IMAGE_H\nold\n#endif\nrest'
        result=runner.replace_abi(source,'#ifndef STUDENT_MINI_NATIVE_IMAGE_H\nnew\n#endif',9)
        self.assertIn('BYTES 9',result);self.assertIn('\nnew\n',result);self.assertNotIn('old',result)


if __name__=='__main__':unittest.main()
