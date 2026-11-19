"""Publish source-bound stage observations without converting them into release gates."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.student_mini import sha

def main():
    sources={
        'cpu_single_buffer_diagnostic':'build/student-mini/cpu-cts-buffer-probe/6be2bac75d0373dccf6c0a3f0d1232aa6b8a358b97c6e808d0455ebbcbf398d8/completion.json',
        'cpu_single_buffer_resource':'grading/evidence/student-mini-v1/environment/cpu-cts-single-buffer-20261008-1640.json',
        'gpu_icache_synthesis_hold':'build/student-mini/gpu-cut-synthesis/16976cb5ea94f48a8837952baf9d4aee788c5dff98c61c85e3a9be04af61ca0f/completion.json',
        'gpu_icache_physical_resource':'grading/evidence/student-mini-v1/environment/gpu-icache-physical-20261008-1533.json',
        'gpu_icache_counter_comparison':'build/student-mini/gpu-icache-counters-continuation/ae5376d2cfb6311efb9b9cc7d503c38727a907f9a4f03a63f5a40fb7e1c0e4a2/completion.json',
        'linux_expanded_source_regression':'grading/evidence/student-mini-v1/full-regressions/20261008T165428200272Z/completion.json',
        'gpu_icache_replay':'build/student-mini/gpu-icache-pipeline/8cc2608076c4cd7e5f8ec112aa44b5780ba098e74b8e9b9502fd5564a7592342/completion.json',
        'gpu_icache_actual':'build/student-mini/gpu-physical-replay/c84868d2c694342891ee320a02ad93a2ed56f5619981a7642357ecb15ed0d38c/completion.json',
        'gpu_icache_resource':'grading/evidence/student-mini-v1/environment/gpu-icache-pipeline-20261008-1523.json',
        'cpu_cts_no_insertion':'build/student-mini/platform-route/adc8207e2fde00c779b8e2c61c431c1ae0ab3c3be902e977950b828142d01dc8/completion.json',
        'linux_bound_regression':'grading/evidence/student-mini-v1/full-regressions/20261008T160750390009Z/completion.json',
        'linux_bound_regression_resource':'grading/evidence/student-mini-v1/environment/full-linux-bound-regression-20261008-1608.json',
        'cpu_dfi_read_reset':'build/student-mini/cpu-inflight-reset/fe82fed18c4e967642763ceebc4c470397c545ec10bed29c54e4f320f3881300/completion.json',
        'cpu_dfi_read_reset_resource':'grading/evidence/student-mini-v1/environment/cpu-inflight-reset-root-fixed-20261008-1559.json',
        'student_p2_ten_seeds':'build/student-mini/student-case-replays/806cc96aadb6740d-20261008T153206249567Z/completion.json',
        'student_p3_ten_seeds':'build/student-mini/student-case-replays/8cece29b8006062e-20261008T153216340402Z/completion.json',
        'student_p2_ten_seeds_resource':'grading/evidence/student-mini-v1/environment/student-p2-ten-seeds-20261008-1532.json',
        'student_p3_ten_seeds_resource':'grading/evidence/student-mini-v1/environment/student-p3-ten-seeds-20261008-1532.json',
        'cpu_cts_derate_hold':'build/student-mini/platform-route/166c7eaf761ab5a153a9f50771dcb068acbb65036138b9a506fd8bea4d361564/completion.json',
        'numeric_coverage_join':'grading/evidence/student-mini-v1/numeric-coverage/56f2e268a8cbdf83a098eeb8e2b4f665fe9a6d4e3b86b7bf9448a1445a4770a4/coverage.json',
        'cpu_quiescent_warm_reset':'build/student-mini/cpu-warm-reset/daa0bfb9aea6834e97c3e544ed6e46d5c6fa915d036da657491961a5969a322f/completion.json',
        'cpu_quiescent_warm_resource':'grading/evidence/student-mini-v1/environment/cpu-warm-reset-recovery-20261008-1517.json',
        'cpu_rom_gate_legalized':'build/student-mini/cpu-drive-eco/382c092c0f2406ff3ec47dc5e4c09bad484521de3a4753c1a3304e78450d4212/completion.json',
        'cpu_channel_cts_hold':'build/student-mini/platform-route/cf64b9d607b004bbfc904f3ee451376ea268572fb9e49559d2a9725cdc336bed/completion.json',
        'cpu_channel_cts_resource':'grading/evidence/student-mini-v1/environment/cpu-channel-route-20261008.json',
        'gpu_6000_hold':'build/student-mini/gpu-repaired-placement/aa432e2b56081439d7a554f14de667dca6f88d75382e7c8dfa8367a6870cf2c1/completion.json',
        'gpu_6000_resource':'grading/evidence/student-mini-v1/environment/gpu-footprint6000-recovery-20261008-1446.json',
        'student_p1_ten_seeds':'build/student-mini/student-case-replays/a8492d3d09deeb38-20261008T145005460835Z/completion.json',
        'student_p1_ten_seeds_resource':'grading/evidence/student-mini-v1/environment/student-p1-ten-seeds-20261008.json',
        'cpu_channel160_hold':'build/student-mini/cpu-placement/5416424a51ee6bbcde9c11198e9fa04cda0004808dfccd687a00e5f69a6377b0/completion.json',
        'cpu_channel160_resource':'grading/evidence/student-mini-v1/environment/cpu-channel160-20261008.json',
        'gpu_initial_place_hold':'build/student-mini/gpu-repaired-placement/3b29d24a5c713061fc2b9eaac679991e6bf7c13590b9c8611262b366a12e2eae/completion.json',
        'gpu_initial_place_resource':'grading/evidence/student-mini-v1/environment/gpu-initial-physical-recovery-20261008-2045.json',
        'student_doctor_a':'grading/evidence/student-mini-v1/environment/student-doctor-a-20261008.log',
        'student_doctor_b_physical':'grading/evidence/student-mini-v1/environment/student-doctor-b-physical-20261008.log',
        'cpu_selected_eco_full':'build/student-mini/selected-cpu-replay/955cc3fae9efa6f9d244e83e0791c6c2f286f4410a30dbe9d14542fb4e04186a/completion.json',
        'cpu_selected_eco_resource':'grading/evidence/student-mini-v1/environment/cpu-selected-recovery-20261008-2045.json',
        'cpu_congestion_geometry':'build/student-mini/congestion-geometry/6f43739273dc625c6751da0a511e4c165d956c19d3499cf004bb5bb9e07b6b45/completion.json',
        'gpu_initial_whole_recovery':'build/student-mini/gpu-initial-replay-continuation/2bcb6779cfabbafee7f63056e147ed000355f45e3f0ef26e5119a396b141f173/completion.json',
        'gpu_initial_whole_resource':'grading/evidence/student-mini-v1/environment/gpu-initial-recovery-20261008-2045.json',
        'cpu_eco_grt_hold':'build/student-mini/platform-route/66b092499769a7a592335d0d8b40090af15275719aed33cb9c668f20ed8d4052/completion.json',
        'cpu_eco_grt_resource':'grading/evidence/student-mini-v1/environment/cpu-drive-eco-route-20261008.json',
        'cpu_congestion_snapshot':'grading/evidence/student-mini-v1/congestion-observations/363e850434f1e494442d7acf0c76b9647de096b86dcd7460dd2b89949f04fb3c/observation.json',
        'cpu_two_gate_eco_hold':'build/student-mini/cpu-drive-eco/9636d2dc0763b7c4fc1faa421ff5746397c640185538052cd01457864fb1d151/completion.json',
        'cpu_three_gate_eco':'build/student-mini/cpu-drive-eco/37c836160d46bc5e22196d187ea57da220ed14b1c438ce403bfb38e924cc56a9/completion.json',
        'cpu_three_gate_eco_resource':'grading/evidence/student-mini-v1/environment/cpu-three-gate-drive-liberty-20261008.json',
        'gpu_initial_difference':'build/student-mini/gpu-divsqrt-initial-difference/32ff08c240db07c8329945f6d05bb68de99d411e63271f0d67747faeb3a783fb/completion.json',
        'gpu_initial_difference_resource':'grading/evidence/student-mini-v1/environment/gpu-initial-difference-20261008.json',
        'gpu_initial_export':'build/student-mini/gpu-initial-export-continuation/ad15019e90a0f76336d99ff3619dfdb844368a831534f8130d04ad119c7eeed2/completion.json',
        'cpu':'build/student-mini/cpu/8d5861348e4981dd0ed519c0c425ee7696bfd29f5963bbd4f70276b5bf7f5ab9/completion.json',
        'gpu':'build/student-mini/gpu/f01b705f2fe4034b78088e3761c0e9c9b37c3c1f95937a170807da8078f44f83/simx-0-1000/completion.json',
        'cpu_resource':'grading/evidence/student-mini-v1/environment/cpu-cgroup-qualified-20261007.json',
        'gpu_resource':'grading/evidence/student-mini-v1/environment/gpu-cgroup-full-20261007.json',
        'p1_resource':'grading/evidence/student-mini-v1/environment/p1-physical-cgroup-20261007.json',
        'p1_place':'build/student-mini/physical/9e2f4b1eee09957ac87161934a82c3a5e69ca4766e44cc3dc65660113942be67/completion.json',
        'p2_place':'build/student-mini/physical/7098c5b0de3c312d97f36edfd7327daf730e93dbf5352836ea14363ab74372d5/completion.json',
        'p3_place':'build/student-mini/physical/bb2a6ff9e6cd81036d3690fc0d6650055c8172fce86e093306f7e9efacb64093/completion.json',
        'p2_route':'build/student-mini/physical/7098c5b0de3c312d97f36edfd7327daf730e93dbf5352836ea14363ab74372d5/route/completion.json',
        'dma_formal':'grading/evidence/student-mini-v1/protocol/a7886e1fe9e48eadd2ee3f78b5e9b3e9d308ac689b28be9744d925dcd89eddfd/dma-bounded.json',
        'dma_contract':'build/student-mini/dma-contract/de72a8536cffeb1cb15d5b2ccdde4007f0c2b5e2bc1f60439363940eea85fc39/report.json',
        'gpu_counter':'grading/evidence/student-mini-v1/counters/e49fee9cfeb3f1a99462efc85f3a25fce45b34b3cd28b410d80925c02788f238/gpu-rtl.json',
        'p3_route':'build/student-mini/physical/bb2a6ff9e6cd81036d3690fc0d6650055c8172fce86e093306f7e9efacb64093/route/completion.json',
        'p3_gate_failure':'build/student-mini/p3-activity/34285131d2bf224feb588c1fcd5290431469013fdab416d1feeb09005011d543/completion.json',
        'p3_rtl_fixed':'build/student-mini/rtl/0e29ff3c212fbbd3ba4d39615fc5c9cd708418a7562d546d68bf71ae91195f93/completion.json',
        'p1_rtl_fixed':'build/student-mini/rtl/37a8476369aae9674a85dd5743a7117dc77db2c237fc5ba0c15be2004a5d0b4b/completion.json',
        'p3_synth_activity':'build/student-mini/p3-activity/cf35a987e5805ba829498975b1023f103d3c643839056ab7afab9a1d3fd9a40e/completion.json',
        'p3_activity_resource':'grading/evidence/student-mini-v1/environment/p3-activity-synth-seeds-20261007.json',
        'p3_place_fixed':'build/student-mini/physical/67a898cb10bc0bb084b627a5e0fc3b923ab7296c4dcfd221c8f0db92193ac1bc/completion.json',
        'p3_place_resource':'grading/evidence/student-mini-v1/environment/p3-place-select-fix-20261007.json',
        'gpu_counter_p2':'grading/evidence/student-mini-v1/counters/6e316267a6051f5a896ba11ffb3230ba3fe88870a8feb00bfe9a279c47a7f990/gpu-rtl.json',
        'gpu_counter_p3':'grading/evidence/student-mini-v1/counters/8450a3aa9df32bb416bb4e26e1254e282138f324b63f309d62afe0fae1f9bebd/gpu-rtl.json',
        'p3_route_fixed':'grading/evidence/student-mini-v1/route-audits/4cc46cee17b564d576e385ab8c602258c98376808d1ad235ab30e629c135947d/audit.json',
        'p3_route_resource':'grading/evidence/student-mini-v1/environment/p3-route-select-fix-20261007.json',
        'p2_context_fixed':'build/student-mini/rtl/5350739617689239f91a40ce7435ccc73d21626df5500d8bcc97714cf6bf6179/completion.json',
        'p2_nano_boundaries':'build/student-mini/rtl/164e3eecee4fa0ef91dfc583abec5f52b868c953d22364beee275bf8b131ce77/completion.json',
        'gpu_first_batch':'grading/evidence/student-mini-v1/counters/bc54d3bd561c08da641782dc50391cbbe318f035dc930866bd3017da7b781747/gpu-rtl.json',
        'p3_gate_activity':'build/student-mini/p3-activity/d032db1e3ccc26ea7a288d2980f112234635a11fedb0b1f5ee6d9bf9614f1da2/completion.json',
        'p3_power':'build/student-mini/power/b88f8b0a985f6eb1f72db5851d416934fc2f35f4699e496b1beba85126ed9cb6/completion.json',
        'p3_power_resource':'grading/evidence/student-mini-v1/environment/p3-power-scope-fixed-20261008.json',
        'p1_place_corrected':'build/student-mini/physical/ff84b504ff538e790ba780bb6948aaa4d005054589fa69ba4e387e29555f5acf/completion.json',
        'p2_place_corrected':'build/student-mini/physical/bb94ec6c721bcc41fe492585422be8550cdbfeef5fc774bb2e7104192d3d30bc/completion.json',
        'cpu_boundary':'build/student-mini/cpu-boundary/f78580114d7b024a2f1a183c14a265e2fc2e21066a9615103ce5a14e808df7b8/completion.json',
        'gpu_boundary':'build/student-mini/gpu-boundary/0a6613e9917f9c713e611fe88a5084486a3936da52079823a0275c486639f9b4/completion.json',
        'gpu_std_p1':'grading/evidence/student-mini-v1/counters/16478dcea66d8d558b2067d4052439c038a83914baad5e53f5b5c054961afa94/gpu-rtl.json',
        'gpu_std_p2':'grading/evidence/student-mini-v1/counters/82d6f42cc3d52009423f0376d528f9677bd2128f5b4d020433fb1974ffff2b13/gpu-rtl.json',
        'gpu_std_p3':'grading/evidence/student-mini-v1/counters/3a2a768a0604579aaf069eb0f637d716048046366689e06d6085a9b2e967b652/gpu-rtl.json',
        'native_c_preflight':'build/student-mini/native-c-preflight/68126edd648b5ff7c94c8342378b1625146b06ad1f7cafd7fe53210589f8c5d5/report.json',
        'native_image':'build/student-mini/native-image/dee82f17962a3df6d0a03567e2564f396e5fb096c2e659ee9bd7ff1169929659/manifest.json',
        'p1_route_timeout':'build/student-mini/physical/ff84b504ff538e790ba780bb6948aaa4d005054589fa69ba4e387e29555f5acf/route/completion.json',
        'p1_route_timeout_resource':'grading/evidence/student-mini-v1/environment/p1-route-resumed-20261008.json',
        'p2_route_signed':'grading/evidence/student-mini-v1/route-audits/af036098ef664ae41de9226b048d307522834cf440f7e26de2337385c83b6be1/audit.json',
        'gpu_native_session':'grading/evidence/student-mini-v1/native-sessions/f0b8b58f8c1043ee1ceaa632b549c5149896ccb5537cd7bb00ee7ef7f7003f6f/session.json',
        'accel_native_session':'grading/evidence/student-mini-v1/native-accelerator-sessions/46e746e32e17d2595495bff07b3bb62f5585d79acb35c3b5c0fe945d395b2c7f/session.json',
        'gpu_adapter_proof':'build/student-mini/gpu-adapter-formal/f2267fbed1f4a12e45dd693047c077383d10257b8fd5986a81977564d40ef131/completion.json',
        'p3_fresh_power':'build/student-mini/sourcebound-power/9bbc553fd8b16c4fdd6791791f81b35ca968cec08429962143f75c1dc7df38e5/completion.json',
        'cpu_combined_build_hold':'build/student-mini/combined-cpu/031f323a192e903f4adf30fd86e112074cc01d11f3e1844f2b9a34fdf410eb87/completion.json',
        'gpu_std_batch':'grading/evidence/student-mini-v1/counters/c5e7774cda6935b7ec65f783b23ba88840ba66dfca2e317814449a7c7c05da8e/gpu-rtl.json',
        'gpu_std_batch_100':'grading/evidence/student-mini-v1/counters/7b0ae3478143da81d21ce002aed88c095edae4dc0bb34f1c5cd794ab62a10100/gpu-rtl.json',
        'cpu_wishbone_proof':'build/student-mini/wishbone-formal/bbbd604121dad1864b9fa90e1622dae936dcf1889cfaf1c1df96eabd9f9e1df0/completion.json',
        'p2_gate_activity':'build/student-mini/attention-activity/76c821f66238a0cd191140a958cddb75e3c738fadc5f9cbda61537b92b52f060/completion.json',
        'gpu_lef_hold':'build/student-mini/gpu-physical/6fbbdf9256df5d091894efa28fff7be1e6767da8a2fc99c7eb8167cb0bafc09f/completion.json',
        'gpu_lef_resource':'grading/evidence/student-mini-v1/environment/gpu-physical-preflight-freshness-fixed-20261008.json',
        'cpu_child_python_hold':'build/student-mini/combined-cpu/56b4c710226ef6afdfee7a5261f9e6d57219c4bb98fbe34a02152d663843660f/completion.json',
        'p3_bundle':'build/student-mini/physical-packages/accelerator-p3/700fc245c1f9476c82dc429388f535b7da23e1c64bc4e3b3de9d373f9ac52cc8/profile.json',
        'p3_bundle_verification':'grading/evidence/student-mini-v1/environment/p3-independent-bundle-verification-20261008.json',
        'gpu_memory_witness':'build/student-mini/gpu-memory-witness/9aa83e529a4cbeb758651f79f226f75856a617b008a498e994573341ecd3785d/completion.json',
        'cpu_mapped_memory':'grading/evidence/student-mini-v1/environment/cpu-mapped-memory-differential-20261008.json',
        'cpu_replay_comparator':'grading/evidence/student-mini-v1/environment/cpu-replay-capture-fixed-20261008.json',
        'orfs_source':'build/student-mini/orfs-declared-export-audit-20261008/audit.json',
        'p1_final_observation':'grading/evidence/student-mini-v1/route-observations/2190e2fda398e21aa2205275870dedc5b43a48e6c7d31818202eabe67485832b/observation.json',
        'p1_final_resource':'grading/evidence/student-mini-v1/environment/p1-route-registered-queue-20261008.json',
        'p2_fresh_power':'build/student-mini/sourcebound-power/f29239b99928e3d4cd32ea43ce0e215be2465f19919d1d7cc0c1c860e3ff738d/completion.json',
        'p2_power_resource':'grading/evidence/student-mini-v1/environment/p2-sourcebound-power-20261008.json',
        'cpu_combined_results':'grading/evidence/student-mini-v1/results/c931ddfc70c2b06e0bcbb7abf9a1fa74c141dbd54e12ab3a57caf53c1dd8332f/results.json',
        'cpu_combined_session':'grading/evidence/student-mini-v1/native-sessions/55707dcad71b142feb56d7eed779193082be7a5778275f0717187331d57a84e8/session.json',
        'cpu_combined_resource':'grading/evidence/student-mini-v1/environment/combined-cpu-child-python-fixed-20261008.json',
        'gpu_macro_name_hold':'build/student-mini/gpu-lef-recovery/83f92e32e78922b54079c678ca74b50be166bf1a167180dbdc149118efa0e8eb/completion.json',
        'gpu_macro_name_resource':'grading/evidence/student-mini-v1/environment/gpu-lef-unit-recovery-20261008.json',
        'gpu_timing_hold':'grading/evidence/student-mini-v1/gpu-timing/eb4c07f9430fffb447688c492f09c669fca38be9cff983b1bf53f79a518a1baf/audit.json',
        'gpu_timing_intervention':'grading/evidence/student-mini-v1/interventions/da3700cff61d5795d7aed7a7c1d472cd24bf4c7ac351f53de70015c0616b4b45/receipt.json',
        'gpu_timing_resource':'grading/evidence/student-mini-v1/environment/gpu-exact-macro-names-recovery-20261008.json',
        'gpu_std_batch_200':'grading/evidence/student-mini-v1/counters/1b2a89b4fd9d79011b87a68afebd90db6789c88c6e04ca1fa5600a3c3afeaa81/gpu-rtl.json',
        'gpu_std_batch_300':'grading/evidence/student-mini-v1/counters/750aecee048ef9608bd2b50888b5317fbdfe9bba4f9d55068693e5ccbdd21e4f/gpu-rtl.json',
        'gpu_std_batch_400':'grading/evidence/student-mini-v1/counters/fd9aa76a56945c30291b63df0a2278b2943e59b5d715e6cbf3b01cf3451d1444/gpu-rtl.json',
        'p2_bundle':'build/student-mini/physical-packages/accelerator-p2/110424462908e8028c97a59b35446544ff91068b76425afc06309a75dcd92e87/profile.json',
        'p2_bundle_verified':'build/student-mini/physical-bundle-continuation/553ae3d9d8e111dd701d551ac1a5dcc47d5a652cafb9c0919c6108d171e25c5c/completion.json',
        'p2_bundle_resource':'grading/evidence/student-mini-v1/environment/p2-physical-bundle-linked-design-20261008.json',
        'p1_registered_gate':'build/student-mini/attention-activity/cbf6840014b610ed57eb849c9bd152f5181c17af331451704578eb336f8ce66d/completion.json',
        'training_retry':'build/student-mini/training-budget-retry/ee64b3add02c915964039004e3fd78434c9a0d2c5a9ef5e382dbacc143e9e89f/completion.json',
        'training_retry_candidate':'build/student-mini/native-nano/ab740c0a3200b4fcb4eb4d49cd9ec06cc057a8220f39dd1a49f5141d0351bf89/candidate.json',
        'p1_antenna_repaired':'grading/evidence/student-mini-v1/route-audits/9403718486cb1c8041ba88bcf98285feb5f51ffc602018247a5cc39a458d6ef9/audit.json',
        'p1_antenna_resource':'grading/evidence/student-mini-v1/environment/p1-additional-antenna-repair-20261008.json',
        'p1_antenna_route':'build/student-mini/antenna-resume/890e33c01568e08ebf97ed3f44f6e018ef83a5379d131250462e5dc1f36e06a8/route/completion.json',
    }
    sources.update({
        'gpu_replay_compile_hold':'build/student-mini/gpu-physical-replay/869fdd4445b27785b5b964c51a3fdf8b6fe76f4c370ecb849b5e7c96a1c7d917/completion.json',
        'native_quality_recheck':'build/student-mini/native-quality/94a578ca63853c7c5e44fbb53cdac639bc0f1955eeba80ce912d6326b68e5e12/audit.json',
        'native_dma_full_contract':'build/student-mini/native-dma-contract/5094d75f292d20fd841da9f0d5849f2ee92d8f41e9ab663b1f0c236c80081912/completion.json',
        'cpu_executed_reset':'build/student-mini/cpu-reset-continuation/954fdc7804e2033da640ffbf345a1747d9890ae85db8b78fa1ae01a4b3a471ac/completion.json',
        'gpu_step_cut_differential':'build/student-mini/gpu-divsqrt-step-cut/af2dfb0341276c7a193e0b0a1c9eac78e75b1cefa5635594fe196ac2dff50113/completion.json',
        'p1_repaired_gate':'build/student-mini/attention-activity/34998e5baf57a0d18257343a9706fe9aedcd65b27fb7e7ead14ae0c28f28829e/completion.json',
        'host_restart':'grading/evidence/student-mini-v1/interventions/host-reboot-20261008T011814-wsl-inventory/snapshot.json',
        'cpu_cold_replay':'build/student-mini/cpu-boundary-replay/cbf0834b5e3b275c7a23d3ac21241297e6022d33f1dfc2ec6788ad6c122e0c26/completion.json',
        'cpu_cold_resource':'grading/evidence/student-mini-v1/environment/cpu-replay-postboot-20261008.json',
        'selected_quality':'build/student-mini/native-quality/a3d26dbabc6a2d889f79edd07247037d3d59a75ea78bae08221f62aaf3fc9a46/audit.json',
        'selected_quality_resource':'grading/evidence/student-mini-v1/environment/nano-quality-selected-postboot-20261008.json',
        'p1_bundle_verified':'build/student-mini/physical-bundle-continuation/35b397ef4a33b2963835d4cb0a9334a9373d8e3aa522c794cdd9bcb81d5103b9/completion.json',
        'p1_bundle':'build/student-mini/physical-packages/accelerator-p1/1d8b47c10454a17175c6a28efef5b8cbc677b1e5c62f3cef37365c527f6b61a2/profile.json',
        'p1_bundle_resource':'grading/evidence/student-mini-v1/environment/p1-bundle-postboot-20261008.json',
        'cpu_synthesis':'build/student-mini/cpu-synthesis/e19f8b53ae16766239e37ceb5dc5314b156b56ac584c18efcc9c41d99dab59b8/completion.json',
        'gpu_stalled_replay':'build/student-mini/gpu-physical-replay-resume/45b53100988f8c4c0bfab23dd0e3e8d6e672543fd8a521b88dd19971ddc2ea8d/completion.json',
        'gpu_600_results':'grading/evidence/student-mini-v1/results/f5924a7bb5ff22f4a0f55993467849b2a40d73400b329bff633f434385c66e01/results.json',
        'gpu_old_counter_stop':'grading/evidence/student-mini-v1/interventions/old-gpu-counter-20261008T022454Z/stop-request.json',
        'gpu_idle_proof':'build/student-mini/gpu-idle-retention/ecc0345e9a96773ec225416cc4060e391cc86f71b90a6783c11e054a308e7be4/completion.json',
        'gpu_read_payload_proof':'build/student-mini/gpu-payload-formal/601f0801c8b005c0f6f06a30629a4f306bb89c17428b9eeb77e118dc4d907e84/completion.json',
        'selected_cpu_session':'grading/evidence/student-mini-v1/selected-native-sessions/c9d33eb63101b330ad6a70f33e5b0dcca61bcc304a51a7898aed3f1c822b839d/session.json',
        'selected_gpu_session':'grading/evidence/student-mini-v1/selected-native-sessions/6b18c9ac7a7d9eb16b6b9434e18fbd6528018acff754f20e1112ed3544023b8c/session.json',
        'selected_accelerator_session':'grading/evidence/student-mini-v1/selected-native-accelerator-sessions/0d45c7f79b5a734c5c2781217883883dab5434b4b1359c019b73af55bb3e6972/session.json',
        'selected_cpu_resource':'grading/evidence/student-mini-v1/environment/selected-mapped-cpu-replay-20261008.json',
        'cpu_initial_pdn_hold':'build/student-mini/cpu-placement/55f8fe4d720ecceebbf70453a74b7073b3f5cc1261fed0ffd589519989c41299/completion.json',
        'gpu_idle_whole_hold':'build/student-mini/gpu-physical-replay/ee94101977f74814470fdfdf4f963bf55da00d814dc9280db8e0ad816f63adb9/completion.json',
        'gpu_port_seam':'build/student-mini/gpu-port-proof/fb12e1082800df682266e3f01a41ca40b97c1414db7adc945ed278a9cc578980/completion.json',
        'cpu_power_connected_timing':'grading/evidence/student-mini-v1/cpu-timing/7118f4a80dc6bc752c9b284ac012fc36b1398c43de55eb919bb4c338fc0bd295/audit.json',
        'cpu_rom_cut':'build/student-mini/cpu-rom-cut/cc20f6627f2c6cb00f58cb20547bf85f8eb9e91e90fff4163454acea122f4dab/completion.json',
        'gpu_port_whole_hold':'build/student-mini/gpu-physical-replay/f3a15eef5fa5351797a118a9c2176259bbf208b939bc56d11d883ba087122a8f/completion.json',
        'gpu_complete_repair_boundary':'build/student-mini/gpu-port-boundary/15c8f22276515056cb2eeddef36542f163026f40fa3ae5f9f6766edbe0958b28/completion.json',
        'cpu_rom_full_replay':'build/student-mini/cpu-boundary-replay/a5345df54c77ba2f150d0cf73322c4aea2070bfae4ab3bbe1c7f17c314a6297f/completion.json',
        'cpu_rom_full_resource':'grading/evidence/student-mini-v1/environment/cpu-rom-cut-full-replay-20261008.json',
        'cpu_rom_synthesis':'build/student-mini/cpu-synthesis/e4b16928fca9b080972c65964197d9465214cc0a25a528c3e4d4f13986e537f4/completion.json',
        'cpu_rom_placement':'build/student-mini/cpu-placement/9315e725761044f5f28c0016c70eef86a15888946aa883c305c3474ce000d631/completion.json',
        'gpu_repaired_whole':'build/student-mini/gpu-physical-replay/0e97a9cc4b137d3ffca53d30ced87229e6e17b11dd850e67595f26899b4bddb0/completion.json',
        'gpu_repaired_synthesis':'build/student-mini/gpu-cut-synthesis/aa9f57b18f496395be016d046a355636db80f079c7fc4fc6070290a0686309c6/completion.json',
        'gpu_repaired_counter_probe':'build/student-mini/gpu-repaired-counters/7c0e516f98540ad8b23f40830ac5db5e5c7a59445f49fdd3e6dd9264aad5f2c3/completion.json',
        'cpu_tag_register_proof':'build/student-mini/cpu-tag-registers/b0f76e4f5338f004000e27ec399c7073aa63eee7f0d13a89a9fdfbf5ea121e26/completion.json',
        'cpu_tag_whole':'build/student-mini/cpu-boundary-replay/adc2824584afbf6135a3221dd5f81839f1c751c50153f30dd5ddd7b7d509c08d/completion.json',
        'cpu_tag_whole_resource':'grading/evidence/student-mini-v1/environment/cpu-tag-full-replay-20261008.json',
        'gpu_repaired_placement_hold':'build/student-mini/gpu-repaired-placement/69441be4d195fd3c9326f3dbb6b31e7d306f56658eeba858bd5eeaa49088610a/completion.json',
        'gpu_nrm_differential':'build/student-mini/gpu-divsqrt-nrm-cut/d791fe3f1faf7da70970369f6bf09eb805bad2f0854f8d6a635f07e243b7b093/completion.json',
        'cpu_tag_placement_hold':'build/student-mini/cpu-placement/8866ad82ec2f0d867aa02a7fbfd21d914c98d7f688027a8490c780a9bf8edb7c/completion.json',
        'cpu_tag_bank_proof':'build/student-mini/cpu-tag-banks/9e7cb24d3842192b75ea48a9e099867fa97e7d149461d6b5da397479d7d32862/completion.json',
        'gpu_nrm_whole':'build/student-mini/gpu-physical-replay/62fa5153aa0d4e3fafe242108b26ea090070fe4942a359431b60ec02c3906f2c/completion.json',
        'gpu_nrm_whole_resource':'grading/evidence/student-mini-v1/environment/gpu-normalization-full-replay-20261008.json',
        'cpu_tag_bank_whole':'build/student-mini/cpu-boundary-replay/0d8e66046234b31b024bcd09b21a3e6bdbc97e34b4af2802c638233b86fdc443/completion.json',
        'cpu_tag_bank_whole_resource':'grading/evidence/student-mini-v1/environment/cpu-tag-bank-full-replay-20261008.json',
        'cpu_tag_bank_synthesis':'build/student-mini/cpu-synthesis/f27ec125f2fc8bef00a6ddc44a2aa6ece27e28e57284acdb01fbcbf59b3950fb/completion.json',
        'gpu_nrm_synthesis':'build/student-mini/gpu-cut-synthesis/a972313dc91e6cdd622efa59e614774014a4a33da7af02b1b543082146311dd2/completion.json',
        'gpu_nrm_counters':'build/student-mini/gpu-repaired-counters/a4f5ae5c4ab037e922c59b5754a8a286560d8805a5a04c7326151258c10ed395/completion.json',
        'cpu_tag_bank_placement_hold':'build/student-mini/cpu-placement/d7df5fd0880eac97dfd4fb5e00cb792c33b17da5ce24d878abd55b80bcedb26c/completion.json',
        'gpu_nrm_placement_hold':'build/student-mini/gpu-repaired-placement/acb759d14718eb142501de74462c5d71234cf359c726b0f8476b1b372eaaffc2/completion.json',
        'gpu_iteration_hold':'grading/evidence/student-mini-v1/gpu-iteration-holds/ea3fd3e441078263aab7d4a74d6344241f35ccedb4c2fe55bbad7ee92fb96f4c/audit.json',
        'gpu_sign_differential':'build/student-mini/gpu-divsqrt-sign-cut/3897518b36dbd9b09d90e283d54ffc93e4c5b183029ea4d9a5d189a1c00bc5e9/completion.json',
        'gpu_sign_whole':'build/student-mini/gpu-physical-replay/d4de1dc4a291fb9a245badb2d088d548913e0497c8697f5bfc7bc0a6a656ae65/completion.json',
        'gpu_sign_synthesis':'build/student-mini/gpu-cut-synthesis/877e508aa67e26c21da2ccad78905aa868598b1bd513cadd7ef887cac024ec7a/completion.json',
        'cpu_request_local':'build/student-mini/cpu-rom-request-proof/951ba2651959d2ae0d528ce0311a8a42af0612ca26a59eaa134ac94c7be81ee7/completion.json',
        'cpu_independent_whole':'build/student-mini/cpu-boundary-replay/e0a41d8385a82aeee9dd369ebcd82fb0dfe8a761ca00c84bade49e0dab9017c0/completion.json',
        'cpu_independent_resource':'grading/evidence/student-mini-v1/environment/cpu-independent-memory-lockstep-20261008.json',
        'cpu_request_formal':'build/student-mini/cpu-rom-request-formal/6744b46e4baf200adbcb9901d88e41254d2b484fd3d76b3a871a6c74ebc8f729/completion.json',
        'gpu_sign_cache_hold':'grading/evidence/student-mini-v1/gpu-cache-holds/b8bebbc810e5b8a6e1c2b5c55602434c7a28eb094a87f738a8248afd931da890/audit.json',
        'gpu_sign_counter_probe':'build/student-mini/gpu-repaired-counters/78b0b56c565018bb8d8ddc90d8b10dfbfc084bae701c89cf36cf1c8f73933a60/completion.json',
        'gpu_sign_multiclass':'build/student-mini/gpu-sign-multiclass-probe/35f0d151570c486227cb8ffc9c561e8fa037c56d8f0ad0b733beb14fda5608dc/completion.json',
        'cpu_request_whole':'build/student-mini/cpu-latency-native-counter-recheck/733c71abdbc634d6c82edf9e5fa65ba65a04d5957da0dd83391e2f1ea893c1e3/revalidated/completion.json',
        'cpu_request_recheck_resource':'grading/evidence/student-mini-v1/environment/cpu-rom-request-counter-recheck-20261008.json',
        'cpu_request_results':'grading/evidence/student-mini-v1/results/311a6debfdba0e72738dffc7f9859b964187cd941261428de03371fc687dad5c/results.json',
        'gpu_report_retry_hold':'build/student-mini/gpu-repaired-placement/95155a590eaef23f2ce585dc139b56992b350feb21915dfa739d40f6eb7d180d/completion.json',
        'gpu_report_retry_resource':'grading/evidence/student-mini-v1/environment/gpu-sign-placement-report-retry-20261008.json',
        'gpu_detail_retry_hold':'build/student-mini/gpu-repaired-placement/ef760dd4a58adb0cd7fc685e7290887bc331ed9759fd3d13c025f8c7189902d5/completion.json',
        'gpu_detail_retry_resource':'grading/evidence/student-mini-v1/environment/gpu-sign-detail-placement-retry-20261008.json',
        'gpu_legalizer_pressure':'grading/evidence/student-mini-v1/gpu-legalization-holds/8bda32764c8f32e581d3bf69d830feff3d9a3fe7dbd50f1671cebf01bd73b0d4/audit.json',
        'cpu_request_synthesis':'build/student-mini/cpu-synthesis/1ca643e6a9a8f759c9df3f42f1d71bdf32bbc12a63656c46780df08ca2d87d53/completion.json',
        'cpu_read_buffer_place':'build/student-mini/cpu-read-buffer-placement/d804aff9c9af2665d1cc099aff8e5f6fe2aee06accabe27bc198bf0d35560c80/completion.json',
        'cpu_read_buffer_route':'build/student-mini/platform-route/926c5788f003c9d45348503bf5742b0ef28de948a9d6c932d4a7c026e554e5ed/completion.json',
        'cpu_negative_cts_stop':'grading/evidence/student-mini-v1/interventions/cpu-negative-cts-e7a3f7738d834af9ba10dc2476b95f2de5dfffa5809bea0f33e013b724ed673b/intervention.json',
        'cpu_read_buffer_route_resource':'grading/evidence/student-mini-v1/environment/cpu-read-buffer-route-20261008.json',
        'gpu_diamond_hold':'build/student-mini/gpu-repaired-placement/6dc6c34af00c2a6974064cd3ae22c014e40f524e4ca1b39ae20d555d63512d31/completion.json',
        'gpu_multiplier_local':'build/student-mini/gpu-multiplier-local-proof/66f0b11d247aaac5db261f5c3d854745b98f0ae7d7e8537c2de905e5bd8631ea/completion.json',
        'cpu_dfi_failed_replay':'build/student-mini/cpu-boundary-replay/437b42a98cc4e03091ef8702147bb77de216af2b683602318048ac5fc4693317/completion.json',
        'cpu_dfi_failure_stop':'grading/evidence/student-mini-v1/interventions/cpu-dfi-replay-failure-1b7454c57ec23abd6aaae5a08986854879cd6ceb48477ba590e74f0e348f568f/intervention.json',
        'cpu_dfi_aligned_mapping':'build/student-mini/cpu-dfi-aligned-boundary/d4980b7d51e08568d8619d1e1665cb3f4c165ea3b63e15def980035f3a8a8555/completion.json',
        'gpu_multiplier_export':'build/student-mini/gpu-multiplier-export-continuation/b7e9f80f0f1f4484ca24c6dfe35b5656f7b85812d2d8ffd69b26bcd939fbd886/completion.json',
        'cpu_dfi_aligned_replay':'build/student-mini/cpu-boundary-replay/f074fc573b626c7a45e40416a2d2441367656e1249b30db74da12c0535402c99/completion.json',
        'cpu_dfi_aligned_resource':'grading/evidence/student-mini-v1/environment/cpu-dfi-aligned-replay-20261008.json',
        'cpu_dfi_aligned_results':'grading/evidence/student-mini-v1/results/301ee27074033c14340e14ffa3e20faa55dcc59650f34bca1496e9a66696d156/results.json',
        'cpu_dfi_aligned_synthesis':'build/student-mini/cpu-synthesis/957e229a73ffa590f8e335968b27acbe12b88f1ebab91c3b5922fe876c8a64f1/completion.json',
        'cpu_dfi_aligned_placement':'build/student-mini/cpu-placement/1cdd7d9fa8e4ad3d3762165a179382cfcb605db5a035857f5085d3f6b31bf29d/completion.json',
        'gpu_multiplier_whole':'build/student-mini/gpu-multiplier-replay-continuation/cdd709359def9decbd0d869da37f7d8cc55a3034107a8688d6d724acab78579f/completion.json',
        'gpu_multiplier_whole_resource':'grading/evidence/student-mini-v1/environment/gpu-multiplier-whole-replay-20261008.json',
        'cpu_multiplier_drive_audit':'grading/evidence/student-mini-v1/cpu-drive-diagnostic/9d560d995f7abc73861bd42b59f4b8080f2dc60d67cbd13d455e5cd426a7c9c2/audit.json',
        'gpu_multiplier_synthesis':'build/student-mini/gpu-cut-synthesis/ff522a87721a4cf71419138b5ae298ef5f47cd56d9fc0390010f6221249d3bf2/completion.json',
        'gpu_multiplier_place_hold':'build/student-mini/gpu-repaired-placement/c83a3e90f5eaf625e60fa05d39c3e3bd7a3eb88033b5f0fbddc835114a2fd2a3/completion.json',
        'gpu_multiplier_physical_resource':'grading/evidence/student-mini-v1/environment/gpu-multiplier-physical-20261008.json',
        'gpu_multiplier_counters':'build/student-mini/gpu-repaired-counters/b4b0fccdb33942c9d0bd8f5ba6df8613644ab6fbfc0d50e474fa402f964220bc/completion.json',
        'gpu_multiplier_multiclass':'build/student-mini/gpu-sign-multiclass-probe/af54a778ae7a386863ae6ef3542b8eb8f8bfff3cc2114985ba0a7ca31cd349c6/completion.json',
        'gpu_multiplier_full_hold':'build/student-mini/gpu-multiplier-full-multiclass-continuation/f216a49ea57bc56558837118eb2d47c29dbdac2e238a21f48f1e00cad8706290/completion.json',
        'numeric_path_components':'build/student-mini/numeric-path-witnesses/de0dc89af1215b07f93baf96eca4a39a47374e4ab4e797a3cb90844634ad06a4/completion.json',
        'numeric_path_contract':'grading/student-mini/numeric-paths-v1.json',
        'numeric_path_resource':'grading/evidence/student-mini-v1/environment/numeric-path-witnesses-20261008.json',
        'cpu_two_gate_diagnostic':'build/student-mini/cpu-multiplier-drive-probe/5d5d76d0e6e9cfce555611f0df37c27a72791fbad077e88a305e62e9c3a5cd11/completion.json',
        'gpu_multiplier_detail_hold':'build/student-mini/gpu-repaired-placement/609d48897e7d50b515bf4c74a763568aa7488e75bf98684e74c2952b3a21310e/completion.json',
    })
    data={key:json.loads((ROOT/path).read_text(encoding='utf-8')) for key,path in sources.items()}
    rows=[]
    for platform in ('cpu','gpu'):
        run=data[platform];resource=data[platform+'_resource']
        if not run['target_run_complete'] or not resource['limits_enforced'] or resource['exit_code']!=0:
            raise ValueError('cannot publish successful bounded execution')
        rows.append(dict(name=platform.upper()+' 功能重放',status='阶段完成／正式 HOLD',records=1000,
                         seconds=run['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
                         cpu_limit=resource['cpu_limit'],memory_limit_bytes=resource['memory_limit_bytes'],
                         note='墙钟仅用于复现预算；不是硬件性能排名。GPU 另需 RTLSIM。'))
    for op in ('p1','p2','p3'):
        run=data[op+'_place']
        rows.append(dict(name=op.upper()+' 历史综合与布局预检',status='HOLD：发现综合位段错误，需重建' if op in ('p1','p3') else '布局时序通过／未布线签核',
                         seconds=run['elapsed_seconds'],placement_wns_ns=run['placement_wns_ns'],
                         memory_peak_bytes=data['p1_resource']['memory_peak_bytes'] if op=='p1' else None,
                         note='10 ns；布局 WNS 不能替代布线后 WNS。'))
    rows.append(dict(name='P2 详细布线',status='HOLD：30 分钟超时',seconds=data['p2_route']['elapsed_seconds'],
                     note='未完成最终 DRC、时序与功耗签核；原始失败日志永久保留。'))
    rows.append(dict(name='DMA 边界形式检查',status='32 步有界检查及可达性通过',
                     note='仅覆盖 mini DMA bridge，不等于完整 CPU 协议、mutation 或正式 B0。'))
    proof=data['dma_contract']
    if proof['status']!='PASS' or proof['mutants_killed']!=8 or not all(r['accepted'] for r in proof['records']):
        raise ValueError('DMA contract proof or mutations did not pass')
    rows.append(dict(name='DMA 读写屏障与故障检出',status='32 步证明通过；8/8 mutation 检出',
                     note='包含地址、数据、字节掩码、响应保持及写后读屏障；仅证明此 DMA 边界，不替代整机协议。'))
    counters=data['gpu_counter']['records']
    if len(counters)!=1 or counters[0]['backend']!='rtlsim':raise ValueError('unexpected representative counter coverage')
    row=counters[0]
    rows.append(dict(name='GPU P1 RTL 计数代表用例',status='1/1000 case×seed；完整输出及来源关联通过',
                     note=f"实测 {row['cycles']} cycles、{row['instructions']} instructions、D-cache {row['cache_bytes']} B、外部内存 {row['dma_bytes']} B；其余计数尚未完成，不能代表全量。"))
    rows.append(dict(name='P3 历史完整布线',status='REJECT：网表拒绝合法描述符',seconds=data['p3_route']['elapsed_seconds'],
                     note='虽然布线后 setup 裕量约 +0.43 ns、DRC=0、antenna=0，真实网表工作负载却返回 BAD_DESCRIPTOR。连续切片已改为绝对位段，必须重建，禁止复用该物理结果。'))
    fixed=data['p3_rtl_fixed']
    if fixed['exit_code'] or fixed['numeric_pass']!=330:raise ValueError('P3 fixed RTL regression incomplete')
    rows.append(dict(name='P3 位段修复 RTL 回归',status='330/330 数值匹配；60 条见证仍 HOLD',seconds=fixed['elapsed_seconds'],
                     note='新综合回归阻止地址对齐检查误读描述符头；此处不代表新网表或新布线已经通过。'))
    fixed=data['p1_rtl_fixed']
    if fixed['exit_code'] or fixed['numeric_pass']!=330:raise ValueError('P1 fixed RTL regression incomplete')
    rows.append(dict(name='P1 位段修复 RTL 回归',status='330/330 数值匹配；60 条见证仍 HOLD',seconds=fixed['elapsed_seconds'],
                     note='地址对齐判定使用绝对位段；历史布局不能替代修复后物理实现。'))
    activity=data['p3_synth_activity'];resource=data['p3_activity_resource']
    if activity['mode']!='synth' or not activity['activity_complete'] or sorted(r['seed'] for r in activity['records'])!=list(range(1,11)):
        raise ValueError('P3 synthesized workload coverage incomplete')
    if resource['exit_code'] or not resource['limits_enforced']:raise ValueError('P3 activity resource check incomplete')
    rows.append(dict(name='P3 修复后综合网表真实工作负载',status='seed 1–10 完整输出匹配',seconds=activity['elapsed_seconds'],
                     memory_peak_bytes=resource['memory_peak_bytes'],
                     note='真实门级仿真，非 RTL 或主机输出；当前是布线前网表，VCD 不可冒充布线后功耗活动。'))
    place=data['p3_place_fixed'];resource=data['p3_place_resource']
    if place['placement_wns_ns']<0 or resource['exit_code']:raise ValueError('P3 new placement failed')
    rows.append(dict(name='P3 修复后综合与布局',status='10 ns 布局时序通过／正式 HOLD',seconds=place['elapsed_seconds'],
                     placement_wns_ns=place['placement_wns_ns'],memory_peak_bytes=resource['memory_peak_bytes'],
                     note='最终布线、布线后工作负载及逐 seed 功耗仍需独立验收。'))
    for op in ('p2','p3'):
        samples=data['gpu_counter_'+op]['records']
        if len(samples)!=1 or samples[0]['operator']!=op or samples[0]['backend']!='rtlsim':raise ValueError('wrong GPU representative sample')
        sample=samples[0]
        rows.append(dict(name='GPU '+op.upper()+' RTL 计数代表用例',status='代表用例完整输出及来源关联通过',
                         note=f"实测 {sample['cycles']} cycles、{sample['instructions']} instructions、D-cache {sample['cache_bytes']} B、外部内存 {sample['dma_bytes']} B；三个代表用例合计仅 3/1000，不能替代全量计数。"))
    audit=data['p3_route_fixed'];resource=data['p3_route_resource']
    if audit['status']!='ROUTE_STAGE_PASS' or resource['exit_code'] or not resource['limits_enforced']:
        raise ValueError('new P3 route/resource audit incomplete')
    for path,digest in audit['bindings'].items():
        if sha(ROOT/path)!=digest:raise ValueError('P3 route audit source changed')
    rows.append(dict(name='P3 修复后完整布线',status='时序／DRC／antenna 阶段通过；完整物理包仍 HOLD',
                     seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
                     note=f"10 ns；布线后 setup 裕量 +{audit['metrics']['wns_ns']:.6f} ns，DRC=0，antenna=0；还需要布线后网表工作负载、逐 seed 功耗及完整来源核验。"))
    for key,total,title in [('p2_context_fixed',340,'P2 context32 版本原测试回归'),('p2_nano_boundaries',150,'P2 Nano 上下文补充回归')]:
        run=data[key]
        if run['exit_code'] or run['numeric_pass']!=total or run['failures']:raise ValueError('P2 context regression incomplete')
        rows.append(dict(name=title,status=f"{total}/{total} 数值／错误状态匹配",seconds=run['elapsed_seconds'],
                         note='原评分测试不变；补充测试覆盖长度 9/16/31/32 与越界 33、split=1/2/4、seed=1–10。补充测试不加入评分分母，也不替代物理或 Nano 会话验收。'))
    batch=data['gpu_first_batch']['records']
    if len(batch)!=100 or sorted(r['ordinal'] for r in batch)!=list(range(100)):
        raise ValueError('first GPU counter batch coverage differs')
    if any(r['backend']!='rtlsim' for r in batch):raise ValueError('non-RTL counter batch')
    rows.append(dict(name='GPU RTL 计数历史第一批',status='100/1000 case×seed 已关联；DPI/ASIC 边界差异 HOLD',
                     note='每条包含 RTLSIM cycles、instructions、DMA/cache 字节及完整输出关联。但当前 RTLSIM 浮点单元为 DPI，ASIC 为 STD，除法/开方延迟不同；这些数值仅作历史诊断，不能绑定 STD 物理包领取性能分。后续 DPI 批次已停止，STD 版本需重新实测。'))
    activity=data['p3_gate_activity']
    if activity.get('mode')!='gate' or activity.get('activity_complete') is not True or sorted(r['seed'] for r in activity['records'])!=list(range(1,11)):
        raise ValueError('P3 post-route workload coverage incomplete')
    rows.append(dict(name='P3 布线后网表真实工作负载',status='seed 1–10 完整输出匹配；活动采集阶段完成',
                     seconds=activity['elapsed_seconds'],
                     note='实际 6_final.v、100 MHz、完整输出和逐 seed VCD；不是布线前综合网表，也不以主机 golden 代替执行。耗时包括单队列等待。'))
    power=data['p3_power'];resource=data['p3_power_resource']
    if power.get('power_complete') is not True or sorted(r['seed'] for r in power['records'])!=list(range(1,11)) or resource['exit_code']:
        raise ValueError('P3 power/resource coverage incomplete')
    powers=[r['power_w']*1000 for r in power['records']]
    coverage=min(r['annotation_percent'] for r in power['records'])
    rows.append(dict(name='P3 100 MHz 布线后逐 seed 功耗',status='10/10 实际 VCD＋SPEF 功耗完成；完整物理包仍 HOLD',
                     seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
                     note=f'10 次平均 {sum(powers)/10:.6f} mW，范围 {min(powers):.6f}–{max(powers):.6f} mW，最低活动标注 {coverage:.5f}%；不同 seed 分别读取活动，未复用同一功耗值。仍需引脚／工具来源及物理包装配验收。'))
    for op in ('p1','p2'):
        run=data[op+'_place_corrected']
        if run['placement_wns_ns']<0 or not run['reason'].startswith('Requested'):
            raise ValueError('corrected placement preflight failed')
        rows.append(dict(name=op.upper()+' 当前修复版本布局预检',status='10 ns 布局通过；完整布线尚待验收',
                         placement_wns_ns=run['placement_wns_ns'],seconds=run['elapsed_seconds'],
                         note='P1 为位段修复后的真实 RTL；P2 支持 Nano context32。布局裕量不代表布线后时序。'))
    for platform in ('cpu','gpu'):
        boundary=data[platform+'_boundary']
        if boundary.get('extraction_complete') is not True:raise ValueError('boundary extraction incomplete')
        rows.append(dict(name=platform.upper()+' mini 物理入口导出',status='源码边界导出完成；物理实现未完成',
                         note='CPU 保留真实 VexRiscv/cache/SRAM/LiteDRAM/DMA，仅切出外部 DFI 模型；仍需边界等价、复位及 SRAM 映射。' if platform=='cpu' else 'GPU 为 1 core/2 warps/4 threads、无 L2、STD 浮点和 PERF 计数器；仍需 SRAM 映射、接口验证、布线与功耗。'))
    for op in ('p1','p2','p3'):
        samples=data['gpu_std_'+op]['records']
        if len(samples)!=1 or samples[0]['operator']!=op:raise ValueError('wrong STD representative sample')
        sample=samples[0]
        rows.append(dict(name='GPU STD 浮点 '+op.upper()+' 代表用例',status='三类硬件计数与完整输出关联通过；全量未齐',
                         note=f"{sample['cycles']} cycles、{sample['instructions']} instructions、cache {sample['cache_bytes']} B、外部内存 {sample['dma_bytes']} B；STD 三条合计仅 3/1000，不能用旧 DPI 数据补齐。"))
    current_batches=[data['gpu_std_batch'],data['gpu_std_batch_100'],data['gpu_std_batch_200'],data['gpu_std_batch_300'],data['gpu_std_batch_400']]
    samples=[r for packet in current_batches for r in packet['records']]
    if len(samples)!=500 or sorted(r['ordinal'] for r in samples)!=list(range(500)):
        raise ValueError('actual STD batch coverage differs')
    if any(r['backend']!='rtlsim' or r['numeric_match'] not in (True,None) or
           any(type(r[k]) is not int or r[k]<0 for k in ('cycles','instructions','dma_bytes','cache_bytes'))
           for r in samples):
        raise ValueError('invalid actual STD hardware sample')
    unresolved=[r for r in samples if r['numeric_match'] is None]
    if len(unresolved)!=10 or any(r['case_id']!='P1-MINI-30' or r['correctness_status']!='HOLD' for r in unresolved):
        raise ValueError('unexpected unresolved GPU counter case')
    if any(packet.get('formal_baseline') is not False for packet in current_batches):
        raise ValueError('partial counters must not claim formal baseline')
    rows.append(dict(name='GPU 当前 STD 浮点全量计数：前五批',status='500/1000 已采集：490 条数值匹配，10 条 DMA 故障 HOLD',
        note='与当前 STD/PERF 源码配置一致；每条保留 cycles、instructions、DMA/cache 原始计数。三种计数模式的 cycles/instructions 必须一致。P1-MINI-30 的 seed 1–10 缺实际 DMA 故障注入，其计数不能领取正确性或性能分；不把已采集数量当作通过数量。ASIC 等价仍待验收。'))
    native=data['native_c_preflight'];image=data['native_image']
    if native.get('hardware_execution') is not False or native.get('numerical_pass') is not True or len(native['records'])!=12:
        raise ValueError('native C preflight incomplete or mislabeled')
    if image.get('contains_expected_tokens') is not False or image.get('target_execution') is not False:
        raise ValueError('native deployment image must remain input-only and unexecuted')
    rows.append(dict(name='Nano 原生 C 部署预检',status='12/12 问题逐 token 完整 logits／隐藏状态匹配；不是目标执行',
                     note=f"真实权重输入镜像 {image['size_bytes']:,} 字节，不含标准答案；C 与 Python 数值相同不等于回答全部正确，模型质量仍为 11/12。CPU 与 GPU 独立目标运行尚待验收，禁止把本机 C 结果记为平台 PASS。"))
    timed=data['p1_route_timeout'];resource=data['p1_route_timeout_resource']
    if timed.get('status')!='HOLD' or not timed.get('reason','').startswith('TimeoutExpired:') or resource['status']!='HOLD':
        raise ValueError('P1 historical timeout observation differs')
    rows.append(dict(name='P1 历史 7,200 秒完整布线尝试',status='HOLD：7,200 秒超时；不是最终 DRC／时序通过',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='详细布线经历多轮天线修复后触发时限，最终 route ODB 未生成。已从 SHA 绑定的全局布线结果建立独立重跑，执行预算延长到 10,800 秒；RTL、10 ns、布局和验收门槛不变，旧 HOLD 永久保留。'))
    audit=data['p2_route_signed']
    if audit['status']!='ROUTE_STAGE_PASS' or audit['metrics']['wns_ns']<0:
        raise ValueError('P2 routed signoff not qualified')
    rows.append(dict(name='P2 context32 完整布线',status='100 MHz 时序／DRC／antenna 阶段通过',
        note=f"最终 setup 裕量 +{audit['metrics']['wns_ns']:.6f} ns、DRC=0、天线 net/pin=0；逐 seed 门级活动、功耗和完整物理包仍待验收。"))
    gpu=data['gpu_native_session'];accel=data['accel_native_session']
    if gpu['status']!='NUMERICAL_SESSION_STAGE_PASS' or accel['status']!='NUMERICAL_OPERATOR_SESSION_STAGE_PASS':
        raise ValueError('native numerical sessions incomplete')
    if gpu['token_sha256']!=accel['token_sha256'] or not gpu['token_sha256']:
        raise ValueError('native token SHA differs')
    rows.append(dict(name='GPU Nano 真实 SimX 会话',status='全部 token／隐藏状态／logits 数值匹配；正式会话仍 HOLD',
        note=f"{len(gpu['records'])} token，逐 token 执行真实权重模型；与加速器算子会话 token SHA 相同。SimX 仅作功能执行，不把其墙钟作为硬件周期或交互性能。"))
    rows.append(dict(name='加速器 Nano RTL 算子会话',status='53 次真实算子调用，全状态数值匹配；混合执行阶段',
        note='P1/P2/P3 使用真实 RTL；剩余模型计算使用主机 C。不得标成完整硬件会话或端到端硬件性能；CPU 同 ROM 会话仍在补齐。'))
    proof=data['gpu_adapter_proof']
    if proof['status']!='ADAPTER_PROTOCOL_STAGE_PASS' or len(proof['records'])!=10 or not all(r['accepted'] for r in proof['records']):
        raise ValueError('GPU adapter proof incomplete')
    rows.append(dict(name='GPU 实际宽度 command／memory adapter',status='32 步有界证明、可达性及 8/8 mutation 通过',
        note='两路 512-bit 数据、26-bit 地址、10-bit tag，覆盖背压、响应保持及复位恢复；不替代 Vortex core、SRAM 等价或外部 DRAM 故障注入。'))
    proof=data['cpu_wishbone_proof']
    if proof['status']!='ADAPTER_PROTOCOL_STAGE_PASS' or len(proof['records'])!=10 or not all(r['accepted'] for r in proof['records']):
        raise ValueError('CPU Wishbone proof incomplete')
    rows.append(dict(name='CPU Wishbone CSR 桥协议证明',status='32 步有界证明、可达性及 8/8 mutation 通过',
        note='限定 full-word classic 访问，主机请求保持至 ACK 或复位；已检查响应保持、地址/数据/方向、错误及复位。不是整个 LiteDRAM 控制器证明，也未宣称部分字节写已证明。'))
    activity=data['p2_gate_activity']
    if activity.get('operator')!='p2' or activity.get('mode')!='gate' or activity.get('activity_complete') is not True or sorted(r['seed'] for r in activity['records'])!=list(range(1,11)):
        raise ValueError('P2 gate workload coverage incomplete')
    rows.append(dict(name='P2 布线后网表真实工作负载',status='seed 1–10 完整输出匹配；独立 VCD 已采集',
        seconds=activity['elapsed_seconds'],note='100 MHz，实际 6_final.v；功耗重放和 PDK 几何核对尚未完成，因此完整物理包仍为 HOLD。'))
    fresh=data['p3_fresh_power']
    if fresh.get('power_complete') is not True or len(fresh['records'])!=10:
        raise ValueError('source-bound P3 power incomplete')
    rows.append(dict(name='P3 新绑定库／寄生参数功耗重放',status='10/10 独立活动完成；几何包装配仍 HOLD',
        note='重新绑定真实库、RC、网表和每个 seed 的 VCD。几何审计发现 DEF 缩进解析及 setRC 参考环境遗漏，已修复后独立重跑，不将旧 HOLD 改成 PASS。'))
    failed=data['cpu_combined_build_hold']
    if failed.get('target_run_complete') is not False or 'CPU build failed' not in failed['reason']:
        raise ValueError('historical CPU build failure differs')
    rows.append(dict(name='CPU baseline＋Nano 同 ROM 构建',status='旧尝试 HOLD；Makefile 依赖修复后重新排队',
        note='旧 Makefile 在替换对象列表前登记了历史 BIOS 依赖。新入口直接复用冻结上游 BIOS 并显式登记选定入口对象；完整链接图和 RV32 编译回归通过，真实重跑结果尚待验收。'))
    failed=data['gpu_lef_hold'];resource=data['gpu_lef_resource']
    if failed.get('preflight_complete') is not False or failed.get('reason')!='RuntimeError: synth failed':
        raise ValueError('GPU physical HOLD cause differs')
    rows.append(dict(name='GPU mini 物理入口：宏 LEF 单位阻碍',status='逻辑综合已产生网表；LEF 读入失败，未进入布局',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='原宏为 2000 DBU/µm，SKY130HD 技术库为 1000 DBU/µm。六份宏坐标均可精确表示；保留原件，独立生成仅单位声明不同的新视图，待 OpenROAD 几何重放与布局验收。不缩放、不舍入、不改时钟。'))
    failed=data['cpu_child_python_hold']
    if failed.get('target_run_complete') is not False or 'CPU build failed' not in failed['reason']:
        raise ValueError('CPU child environment HOLD differs')
    rows.append(dict(name='CPU 隔离环境：构建子命令解释器修复',status='BIOS 编译链接已完成；校验生成失败后重新排队',
        note='直接调用 venv Python 不会自动改变 PATH；嵌套 python3 曾选到系统解释器而无法导入 LiteX。已验证修复后的子命令使用同一个冻结 venv；尚未把最小环境测试冒充 CPU 运行通过。'))
    package=data['p3_bundle'];validation=data['p3_bundle_verification']
    if package.get('physical_evidence_complete') is not True or validation.get('exit_code')!=0:
        raise ValueError('P3 raw physical bundle verification incomplete')
    log=ROOT/'grading/evidence/student-mini-v1/environment/p3-independent-bundle-verification-20261008.log'
    receipt=json.loads(log.read_text().splitlines()[-1])
    if receipt.get('status')!='PHYSICAL_BUNDLE_VERIFIED' or receipt['profile_sha256']!=sha(ROOT/sources['p3_bundle']):
        raise ValueError('P3 independent physical receipt differs')
    sources['p3_bundle_verification_log']=log.relative_to(ROOT).as_posix()
    rows.append(dict(name='P3 原始物理证据包独立校验',status='P3 原始物理包已通过 v2 校验；正式 B0 仍 HOLD',
        seconds=validation['elapsed_seconds'],memory_peak_bytes=validation['memory_peak_bytes'],
        note='10 ns、时序／DRC／antenna、10 个 seed 的实际活动与功耗、原始证据及包内 SHA 均已核对。当前工具身份仍含 launcher，完整工具实际载荷／依赖的来源与学生可复现环境尚未闭合；不把原始物理包校验混同为最终工具链或 baseline 验收。'))
    memory=data['gpu_memory_witness']
    if memory['status']!='MAPPED_MEMORY_WITNESS_STAGE_PASS' or len(memory['records'])!=40 or memory['whole_core_equivalence'] is not False:
        raise ValueError('GPU mapped memory witness differs')
    rows.append(dict(name='GPU 当前配置实际 SRAM 行为重放',status='4 种可达形状 × seed 1–10 全部匹配',
        note='实际映射共 37 个宏实例；原始输入、逐次读回、golden 和 delta 均保留。覆盖各地址、写掩码、独立端口及复位后保留数据；不宣称同地址读写碰撞、空闲输出保持或整核 ASIC 等价已证明。'))
    for key,count,label,note in (
        ('cpu_mapped_memory',61,'CPU 映射后存储差分回放',
         '6 种实际存储规格 × seed 1–10，原 RTL、综合映射后的真实宏模型与 golden 逐拍比较；包含有定义的写后读、部分字节写、地址 bank 和空闲保持。cache 未定义的同地址碰撞不据此签发通过；整颗 CPU 回放仍待运行。'),
        ('cpu_replay_comparator',13,'CPU 整机比较器与原始日志完整性自检',
         'DFI 地址篡改会被拒绝；真实固件前缀、1,000 个唯一 ordinal、计数器、token/状态完整性和 UART/宏诊断交错均有负例。修复前失败与仅等待任务的取消记录保留；不是完整 CPU 或 baseline 通过。')):
        resource=data[key]
        log=ROOT/sources[key].replace('.json','.log')
        if resource.get('exit_code')!=0 or resource.get('limits_enforced') is not True or f'{count} passed' not in log.read_text():
            raise ValueError('CPU regression stage incomplete: '+key)
        sources[key+'_log']=log.relative_to(ROOT).as_posix()
        rows.append(dict(name=label,status=f'{count} 项回归通过；部件／检查器阶段',
            seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],note=note))
    flow=data['orfs_source']
    if flow['status']!='ORFS_EXECUTED_SOURCE_STAGE_PASS' or flow['differences'] or len(flow['prior_bound_files'])!=96:
        raise ValueError('executed ORFS source audit incomplete')
    rows.append(dict(name='实际 ORFS 流程来源',status='157 个文件、96 个历史输入绑定核对通过',
        note='锁定 aabf2a39 commit；30 处完整 LF→CRLF 转换明示留档，没有未解释修改。实际工具二进制身份与源码子模块指针分开核验；完整学生环境仍待通过。'))
    observed=data['p1_final_observation'];resource=data['p1_final_resource']
    if observed['status']!='HOLD' or observed['wns_ns']<0 or observed['drc']!=0 or observed['antenna_nets']!=2 or observed['antenna_pins']!=2:
        raise ValueError('P1 final routed observation differs')
    folder=Path(sources['p1_final_observation']).parent
    for name,digest in observed['artifacts'].items():
        path=folder/name
        if sha(ROOT/path)!=digest:raise ValueError('portable P1 raw report changed')
        sources['p1_final_raw_'+name]=path.as_posix()
    rows.append(dict(name='P1 上一版完整布线结果（历史 HOLD）',status='100 MHz 时序与 DRC 通过；2 net / 2 pin 天线 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note=f"最终 setup WNS +{observed['wns_ns']:.6f} ns、hold +{observed['hold_wns_ns']:.6f} ns，DRC=0。严格审计拒绝天线违规；从已完成的详细布线检查点独立增加 3 轮修复，RTL、布局和 10 ns 不变。正式物理包不通过。"))
    fresh=data['p2_fresh_power'];resource=data['p2_power_resource']
    if fresh.get('power_complete') is not True or sorted(row['seed'] for row in fresh['records'])!=list(range(1,11)) or resource['exit_code']:
        raise ValueError('P2 source-bound power incomplete')
    powers=[r['power_w']*1000 for r in fresh['records']]
    rows.append(dict(name='P2 100 MHz 新绑定逐 seed 功耗',status='10/10 真实 VCD＋SPEF 功耗完成；独立物理包验收见后续记录',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note=f"平均 {sum(powers)/10:.6f} mW，范围 {min(powers):.6f}–{max(powers):.6f} mW，最低活动标注 {min(r['annotation_percent'] for r in fresh['records']):.5f}%。逐 seed 独立活动，不共享功耗数值；此结果不自动签发 B0。"))
    records=data['cpu_combined_results']['records'];session=data['cpu_combined_session'];resource=data['cpu_combined_resource']
    if len(records)!=1000 or not all(r['observation']['numeric_match'] for r in records) or resource['exit_code']:
        raise ValueError('same-ROM numerical baseline incomplete')
    if session['status']!='NUMERICAL_SESSION_STAGE_PASS' or session['token_sha256']!=gpu['token_sha256']:
        raise ValueError('same-ROM CPU Nano join differs')
    rows.append(dict(name='CPU baseline＋Nano 同 ROM 实际执行',status='1,000/1,000 数值匹配；Nano 全状态匹配；正式 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='真实 VexRiscv RTL 执行一份 ROM；逐条原始计数、输入、golden、actual、delta 已保留。11 个 token 与 GPU/加速器算子会话一致；映射后整机回放、协议、物理和模型质量仍分别待验收。'))
    hold=data['gpu_macro_name_hold'];resource=data['gpu_macro_name_resource']
    if hold.get('openroad_macro_geometry_equal') is not True or hold.get('preflight_complete') is not False or hold.get('reason')!='RuntimeError: place failed':
        raise ValueError('GPU macro-name HOLD observation differs')
    log=ROOT/'build/student-mini/gpu-lef-recovery/83f92e32e78922b54079c678ca74b50be166bf1a167180dbdc149118efa0e8eb/place.log'
    if 'MPL-0020' not in log.read_text():raise ValueError('missing actual macro-name failure')
    sources['gpu_macro_name_log']=log.relative_to(ROOT).as_posix()
    rows.append(dict(name='GPU LEF 单位恢复后的实际预检',status='宏几何逐项一致；宏实例名称解析失败，尚未完成布局',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='六份宏视图由 OpenROAD 分别读取后几何一致，实际 floorplan 已保存。数据库对层级方括号保存反斜线转义，原摆放脚本名称未转义而触发 MPL-0020。新入口保留全部 37 个宏、坐标、网表和 10 ns，从保存的 floorplan 续跑；不能将早期约 −16.6 ns 的修复中间值视为最终布局或布线时序。'))
    verification=data['p2_bundle_verified'];package=data['p2_bundle'];resource=data['p2_bundle_resource']
    if (verification['status']!='PHYSICAL_BUNDLE_VERIFIED' or verification['profile_sha256']!=sha(ROOT/sources['p2_bundle'])
        or package.get('physical_evidence_complete') is not True or resource['exit_code']):
        raise ValueError('P2 independent physical bundle incomplete')
    rows.append(dict(name='P2 原始物理证据包独立校验',status='P2、P3 共 2/5 原始物理包通过；正式 B0 仍 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='P2 的 100 MHz 时序、DRC、antenna、原始 DEF/网表/寄生参数及 10 个 seed 的活动功耗已独立核对。完整平台协议、工具链与 Nano 等门仍未关闭，不签发正式 B0 或学生 ZIP。'))
    gate=data['p1_registered_gate']
    if gate.get('activity_complete') is not True or sorted(r['seed'] for r in gate['records'])!=list(range(1,11)):
        raise ValueError('P1 registered gate replay incomplete')
    rows.append(dict(name='P1 已布线网表的门级活动重放',status='10/10 seed 完整输出匹配；该版本天线仍 HOLD',
        note='保留本次真实 VCD 与输出证据。天线失败正确阻止后续功耗及物理放行；修复后的新网表必须重新执行活动采集，不能借用这批结果。'))
    retry=data['training_retry'];candidate=data['training_retry_candidate']
    if retry['candidate_sha256']!=sha(ROOT/sources['training_retry_candidate']) or any(sum(r['passed'] for r in values)!=12 for values in candidate['quality'].values()):
        raise ValueError('training retry evidence differs')
    rows.append(dict(name='Nano 单变量训练预算复验',status='FP32/PTQ/QAT 的 12 题回归均通过；未替换平台模型',
        note='只将 FP32 步数从 1500 增到 3000，seed=1、数据划分和 QAT 500 步不变。QAT 训练时选定验证结果为 7/8，正在独立检查精确量化验证集。已观察的测试题仅算回归，不冒充新盲测；页面原会话仍绑定旧模型。'))
    audit=data['p1_antenna_repaired'];resource=data['p1_antenna_resource'];route=data['p1_antenna_route']
    metrics=audit['metrics']
    if (metrics['clock_period_ns']!=10 or metrics['wns_ns']<0 or any(metrics[k]!=0 for k in ('drc','antenna_nets','antenna_pins'))
        or route.get('source_freshness_verified') is not True or resource['exit_code']):
        raise ValueError('P1 repaired route audit incomplete')
    rows.append(dict(name='P1 天线修复后的最新布线审计',status='100 MHz、WNS≥0、DRC=0、antenna=0；新网表活动功耗排队',
        seconds=route['route_elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note=f"最终 WNS +{metrics['wns_ns']:.6f} ns。只延长已完成详细布线的天线修复，实际加入 2 个二极管，RTL 和 10 ns 不变。新网表仍须单独采集 10 个 seed 的活动和功耗，再独立装配物理包；此处不是完整物理或 B0 PASS。"))
    timing=data['gpu_timing_hold'];intervention=data['gpu_timing_intervention'];resource=data['gpu_timing_resource']
    if (timing['status']!='HOLD_NEGATIVE_100MHZ_SETUP' or timing['clock_period_ns']!=10 or timing['wns_ns']>=0
        or intervention['status']!='NEGATIVE_TIMING_HOLD_RECORDED' or intervention['wns_ns']!=timing['wns_ns']):
        raise ValueError('GPU negative-timing HOLD receipt differs')
    folder=Path(sources['gpu_timing_hold']).parent
    for name,digest in timing['artifacts'].items():
        path=folder/name
        if sha(ROOT/path)!=digest:raise ValueError('GPU portable timing artifact changed')
        sources['gpu_timing_raw_'+name]=path.as_posix()
    rows.append(dict(name='GPU 当前物理候选：100 MHz 时序预检 HOLD',status=f"修复后 WNS {timing['wns_ns']:.5f} ns；已停止后续布局，不启动布线",
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='宏名称问题已解决。最差路径位于 STD 浮点除法／开方的相邻 SRT 级，一个周期内包含两步运算。STA、网表和停止回执均保留；独立准备单步流水切分并先做 RTL 差分，未采用为正式配置。若延迟改变，旧计数不得复用。'))
    quality=data['native_quality_recheck']
    if quality['status']!='HOLD_VALIDATION_OR_REGRESSION' or quality['selection']['validation_counts']!={'fp32':8,'ptq_exact':7,'qat_exact':7}:
        raise ValueError('independent quality observation differs')
    rows.append(dict(name='Nano 精确部署验证集独立复核',status='HOLD：PTQ、QAT 均为 7/8，不能以测试集 12/12 替代',
        note='天气验证题被错误回答为问候语；未替换平台模型。下一实验仅用精确 INT8/BF16 验证集选择 checkpoint，训练数据、规格和精度不变；测试题不参与选择。'))
    proof=data['native_dma_full_contract']
    if proof['status']!='NATIVE_DMA_ADAPTER_CONTRACT_STAGE_PASS' or proof['depth']!=32 or len(proof['records'])!=10 or not all(r['accepted'] for r in proof['records']):
        raise ValueError('native DMA full contract incomplete')
    rows.append(dict(name='实际 128-bit Native DMA 完整载荷协议',status='32 步证明、4 个可达场景、8/8 mutation 检出',
        note='涵盖地址、数据、字节掩码、读写屏障、错误、背压、响应保持及复位恢复；仅此适配器，不能替代 LiteDRAM、DFI 或整机协议。'))
    reset=data['cpu_executed_reset']
    if reset['status']!='RESET_STORAGE_PROJECTION_STAGE_PASS' or reset['reset_equivalence'] is not False:
        raise ValueError('CPU reset boundary observation differs')
    rows.append(dict(name='CPU 同 ROM ASIC 复位与存储边界导出',status='导出阶段通过；存储映射、冷启动及热复位仍待验证',
        note='保持已执行的 ROM 和实际 VexRiscv/cache/LiteDRAM 边界；这不是复位等价证明或物理实现通过。'))
    replay=data['gpu_replay_compile_hold']
    if replay['status']!='HOLD' or replay['target_run_complete'] is not False:
        raise ValueError('GPU replay compile HOLD differs')
    rows.append(dict(name='GPU 完整物理边界回放编译检查',status='历史 HOLD：导出常量函数的 generate 语法不兼容',
        note='未进入数值执行。最小复现确认后，只展开两个已核对语义和位宽的常量调用；完整边界加真实 SRAM 模型已通过编译检查。新实际回放独立排队，不冒充数值 PASS。'))
    unit=data['gpu_step_cut_differential']
    if (unit['status']!='SRT_STEP_CUT_DIFFERENTIAL_STAGE_PASS' or unit['records']!=35251
        or sorted(map(int,unit['seeds']))!=list(range(1,11)) or sum(unit['seeds'].values())!=unit['records']
        or unit['old_counters_reusable'] is not False):
        raise ValueError('GPU SRT differential evidence differs')
    rows.append(dict(name='GPU SRT 单步流水切分差分',status='35,251 条输出／标志位匹配；10 个 seed',
        note='覆盖 F32 除法、开方、舍入模式、特殊值、停顿、空泡和复位。延迟由 17 拍变为 30 拍；旧计数不能复用。仅单元差分，不是 IEEE formal、整机等价或 100 MHz 时序通过。'))
    gate=data['p1_repaired_gate']
    if gate.get('activity_complete') is not True or gate.get('mode')!='gate' or sorted(r['seed'] for r in gate['records'])!=list(range(1,11)):
        raise ValueError('P1 repaired-netlist activity incomplete')
    rows.append(dict(name='P1 天线修复后新网表工作负载',status='10/10 seed 完整输出匹配，活动已重新采集',
        note='绑定修复后新网表，没有复用旧天线失败版本的 VCD；接下来核验 PDK 几何、逐 seed 功耗及独立物理包。当前原始物理包总数仍为 2/5。'))
    interruption=data['host_restart']
    if interruption['status']!='INCOMPLETE_TASKS_INTERRUPTED_NOT_PASS' or interruption['lost_resource_peaks_reconstructed'] is not False:
        raise ValueError('restart recovery must not fabricate lost resource evidence')
    rows.append(dict(name='主机重启与可恢复续跑',status='09:18 主机重启；中断任务不算 PASS',
        note='9 个未完成任务目录已先保存文件 SHA 清单，再移动为带 interrupted 后缀的可恢复副本。已完成证据未覆盖；丢失的 cgroup 峰值不补造。恢复后的执行单独记录资源。'))
    replay=data['cpu_cold_replay'];resource=data['cpu_cold_resource']
    if (replay['status']!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS' or replay.get('cold_start_replay_complete') is not True
        or replay['transcript_join']['baseline_records']!=1000 or replay['transcript_join']['native_completion'] is not True
        or replay.get('warm_reset_qualified') is not False or resource['status']!='PASS' or not resource['limits_enforced']
        or resource['memory_peak_bytes']>8*1024**3 or resource['cpu_limit']!=2):
        raise ValueError('mapped CPU cold replay/resource evidence differs')
    rows.append(dict(name='CPU 真实 SRAM 映射后整机冷启动回放',status='1000 条 baseline 与完整 Nano 状态、计数匹配；阶段通过',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='100 MHz 实际 SRAM 延迟保留，DFI 与 UART 有效事务逐周期比对；同 ROM 全部原始输出与计数一致。峰值约 4.64 GiB。热复位、完整协议、物理时序功耗与新版模型会话仍是独立门。'))
    quality=data['selected_quality'];resource=data['selected_quality_resource']
    if (quality['status']!='REFERENCE_QUALITY_STAGE_PASS' or quality['selection']['stage']!='ptq_exact'
        or quality['selection']['validation_counts']['ptq_exact']!=8 or quality['question_contamination']!=0
        or not all(r['passed'] for r in quality['regression']['ptq_exact']) or len(quality['regression']['ptq_exact'])!=12
        or resource['status']!='PASS'):
        raise ValueError('selected reference quality stage differs')
    rows.append(dict(name='Nano 精确验证集选模后的独立复核',status='选中 PTQ：验证 8/8，回归 12/12；参考阶段通过',
        note='保持训练 seed、数据、模型规格和精度；以精确部署语义的验证集选择 checkpoint。测试题不参与选择，但已被观察，仍只称回归。新镜像显式绑定 PTQ；旧平台会话不能充当新模型实测，CPU/GPU/加速器需分别重放。'))
    replay=data['gpu_stalled_replay']
    if replay['status']!='HOLD' or replay['target_run_complete'] is not False or replay['records']:
        raise ValueError('stalled whole-GPU replay must remain HOLD')
    rows.append(dict(name='GPU 真实 SRAM 整机回放停滞',status='HOLD：命令环接受后未退休；未产生可用输出',
        note='只终止已核对 PID、可执行文件、参数和工作目录的停滞进程。分别验证 SRAM 空闲输出保持和 DCR 读取参数两个问题；单元修复不等于整机已修复，旧 adapter formal 未覆盖真实读选择参数。'))
    result=data['gpu_600_results']
    measured=[r for r in result['records'] if r['observation']['cycles'] is not None]
    if (result['rtl_counter_records']!=600 or len(measured)!=600 or result['rtl_counter_coverage_complete'] is not False
        or sum(r['observation']['numeric_match'] is True for r in measured)!=590):
        raise ValueError('600-record independent counter join differs')
    rows.append(dict(name='GPU STD 前六批硬件计数独立合并',status='600/1000：590 条数值匹配，10 条 DMA 故障仍 HOLD',
        note='每条包含真实 cycles、instructions、DMA/cache 流量。计数对应旧 17 拍除法配置，不可转借给 30 拍时序修复候选；旧配置余下批次已停止并保留 HOLD，最终候选必须重新完整采集，正式收益资格仍为 false。'))
    synthesis=data['cpu_synthesis']
    if synthesis['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS' or synthesis['physical_evidence_complete'] is not False:
        raise ValueError('CPU synthesis stage differs')
    rows.append(dict(name='CPU 同 ROM 与 30 个真实 SRAM 宏综合',status='综合规模预检通过；初始布局与 100 MHz 时序待检查',
        note='保留已回放的完整 CPU/cache/LiteDRAM 边界和 ROM，不模拟大存储器。综合成功不等于布局布线或物理 PASS，负 WNS 将禁止继续 route。'))
    bundle=data['p1_bundle_verified'];profile=data['p1_bundle'];resource=data['p1_bundle_resource']
    if (bundle['status']!='PHYSICAL_BUNDLE_VERIFIED' or bundle['physical_evidence_complete'] is not True
        or profile['physical_evidence_complete'] is not True or profile['operator']!='p1' or resource['status']!='PASS'):
        raise ValueError('P1 independent physical bundle differs')
    rows.append(dict(name='P1 原始物理证据包独立校验',status='P1/P2/P3 共 3/5 原始物理包通过；正式 baseline 仍 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='P1 在 100 MHz 下 WNS +0.535556 ns、DRC=0、antenna=0；修复后网表的 10 个 seed 活动和功耗重新绑定并离线核对。CPU/GPU 物理包、完整协议、新版 Nano、资源和交付门仍须分别关闭。'))
    stopped=data['gpu_old_counter_stop'];idle=data['gpu_idle_proof'];proof=data['gpu_read_payload_proof']
    if (stopped['preserved_verified_records']!=600 or stopped['final_candidate_requires_full_1000_records'] is not True
        or idle['status']!='GPU_IDLE_RETENTION_MACRO_STAGE_PASS' or len(idle['records'])!=40
        or idle['whole_gpu_equivalence'] is not False or idle['same_address_collision_qualified'] is not False
        or proof['status']!='GPU_READ_PAYLOAD_PROTOCOL_STAGE_PASS' or len(proof['records'])!=12
        or not all(r['accepted'] for r in proof['records'])):
        raise ValueError('GPU private repair stage evidence differs')
    rows.append(dict(name='GPU 两项独立修复的局部验证',status='4 种 SRAM × 10 seed 通过；DCR 32 步证明及 9 个 mutation 通过',
        note='原始 DCR 读参数错误先由增强性质复现，再验证私有修复；SRAM 修复保持空闲输出且不改变读延迟。同地址读写冲突、整机执行和新网表时序仍未证明。已停止不能用于 30 拍候选的旧配置后续计数，完整测试集合不删减。'))
    sessions=[data['selected_'+name+'_session'] for name in ('cpu','gpu','accelerator')]
    if (len({r['token_sha256'] for r in sessions})!=1 or not sessions[0]['token_sha256']
        or any(r['deployment']['stage']!='ptq_exact' or len(r['records'])!=11
               or r['physical_complete'] is not False or r['quality_complete'] is not False for r in sessions)
        or len({r['deployment']['quantized_sha256'] for r in sessions})!=1):
        raise ValueError('selected three-backend numerical sessions differ')
    resource=data['selected_cpu_resource']
    if resource['status']!='PASS' or resource['memory_peak_bytes']>8*1024**3:raise ValueError('selected CPU resource replay failed')
    rows.append(dict(name='新版 PTQ 三路径 Nano 完整数值比对',status='CPU／GPU／RTL 算子混合路径：各 11 token、hidden、logits 一致',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='部署显式绑定验证集选中的同一个 PTQ checkpoint。CPU 实际映射后 RTL 与原 1000 条 baseline 共用不变 ROM，峰值约 1.84 GiB；GPU 是 SimX 功能执行；加速器其余模型计算仍在主机 C。正式会话与硬件性能未放行，不能算 Nano 3/3 最终验收。'))
    pdn=data['cpu_initial_pdn_hold']
    if pdn['status']!='HOLD' or pdn['reason']!='RuntimeError: CPU do-2_4_floorplan_pdn failed':raise ValueError('CPU PDN HOLD differs')
    rows.append(dict(name='CPU 初始物理预检：SRAM 电源连接',status='HOLD：30 个宏已放置，PDN 检出未接电源；未进入 route',
        note='OpenRAM vccd1/vssd1 未绑定平台 VDD/VSS。原记录保留，恢复任务仅增加已有电源连接脚本，并在生成数据库中逐一核对 30 个宏的 60 个供电引脚；RTL、时钟和宏几何不变。'))
    whole=data['gpu_idle_whole_hold'];port=data['gpu_port_seam']
    if (whole['status']!='HOLD' or whole['target_run_complete'] is not False or whole['records']
        or port['status']!='GPU_PORT_PACKING_SEAM_STAGE_PASS' or port['whole_core_equivalence'] is not False
        or len(port['records'])!=20 or not all(r['accepted'] for r in port['records'])):
        raise ValueError('GPU port diagnosis must not masquerade as whole-core success')
    for variant in ('original','fixed'):
        if sorted(r['seed'] for r in port['records'] if r['variant']==variant)!=list(range(1,11)):
            raise ValueError('port seam seed coverage differs')
    rows.append(dict(name='GPU SRAM 保持修复后的整机回放',status='HOLD：命令仍未退休，120 秒看门狗退出',
        note='证实 SRAM 空闲保持的局部修复不足以解决整机卡住；未产生可用内核输出，没有计为 GPU 通过。'))
    rows.append(dict(name='GPU 双端口控制／数据关联修复',status='原实现 10/10 seed 复现错误；私有修复 10/10 seed 通过',
        note='实际 sv2v 导出把端口 0 放在高位，而物理 top 原来使用低位。只修六处核心侧 payload 切片，外侧接口不变；真实适配器的双端口、背压、响应保持及复位共 640 轮通过。核心用匹配实际 ABI 的测试驱动替代，因此这是接口局部证据，完整 GPU 回放仍在独立验证。'))
    cpu_timing=data['cpu_power_connected_timing'];rom=data['cpu_rom_cut']
    if (cpu_timing['status']!='HOLD_NEGATIVE_100MHZ_SETUP' or cpu_timing['wns_ns']>=0
        or cpu_timing['rom_words']!=12558 or rom['status']!='CPU_ROM_CUT_MAPPING_STAGE_PASS'
        or rom['rom_differential_records']!=37888 or rom['macro_count']!=30 or rom['read_latency_cycles']!=1
        or rom['whole_core_equivalence'] is not False):raise ValueError('CPU timing/ROM stage differs')
    rows.append(dict(name='CPU 电源修复后的完整布局预检',status='HOLD：100 MHz WNS −4.36861 ns；已禁止 route',
        placement_wns_ns=cpu_timing['wns_ns'],
        note='30 个宏的 60 个电源引脚连接已通过真实数据库核查。独立 STA 审计确认最差核心路径终止于 12,558 字程序 ROM 输出；不能拿正裕量的复位恢复路径冒充核心时序通过。'))
    rows.append(dict(name='CPU ROM 输出寄存器分组候选',status='37,888 条四态输出匹配；30 个 SRAM 宏结构保持',
        note='逐一检查 32,768 地址及 10 seed 的 5,120 条随机访问，并验证拍间输出保持；ROM 字节、总线握手和对外一拍读延迟不变。完整 CPU 回放、新综合与新布局仍为后续独立门，不计优化晋升。'))
    port_whole=data['gpu_port_whole_hold'];boundary=data['gpu_complete_repair_boundary']
    if (port_whole['status']!='HOLD' or port_whole['target_run_complete'] is not False
        or boundary['status']!='GPU_PORT_REPAIRED_BOUNDARY_STAGE_PASS' or boundary['arithmetic_latency']!=30
        or boundary['simulation_asic_equivalence'] is not False):raise ValueError('GPU whole/structural stages differ')
    rows.append(dict(name='GPU 端口修复后的完整回放',status='HOLD：真实物理命令背压断言失败',
        note='没有删除断言或伪造内核输出。仿真主机在读取响应后过早发下一条命令；连续读取的小型复现已定位握手周期问题，主机侧修复正在独立整机回放。该失败记录永久保留。'))
    rows.append(dict(name='GPU 30 拍完整接口修复边界',status='37 个实际 SRAM 宏的结构检查通过；物理与整机仍 HOLD',
        note='私有候选整合已单独验证的算术切分、SRAM 空闲保持、DCR 读参数和端口排列修复。没有覆盖原 RTL 或旧证据；旧 17 拍性能计数不能复用。'))
    replay=data['cpu_rom_full_replay'];resource=data['cpu_rom_full_resource'];synth=data['cpu_rom_synthesis'];placement=data['cpu_rom_placement']
    if (replay['status']!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS' or replay['transcript_join']['baseline_records']!=1000
        or not replay['transcript_join']['native_completion'] or resource['status']!='PASS' or not resource['limits_enforced']
        or resource['memory_peak_bytes']>8*1024**3 or synth['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS'
        or placement['status']!='HOLD' or placement['placement_wns_ns']>=0 or not placement['macro_power_connected']):
        raise ValueError('ROM-cut whole replay and negative placement stages differ')
    rows.append(dict(name='CPU ROM 切分后的整机与新布局',status='完整 1000 条回放及综合通过；布局 WNS −2.20265 ns，仍 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],placement_wns_ns=placement['placement_wns_ns'],
        note='原 ROM 的全部结果、计数和 Nano 状态匹配，峰值约 4.70 GiB。新关键路径从 ROM 转移到 cache 标签 SRAM 输出至数据 SRAM 写控制，只有半周期；未启动失败布局的 route。该回放使用旧模型，新选中 PTQ 模型仍须绑定最终硬件。'))
    replay=data['gpu_repaired_whole']
    if (replay['status']!='PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS' or replay['target_run_complete'] is not True
        or replay['all_case_coverage'] is not False or replay['performance_eligible'] is not False
        or sorted(r['operator'] for r in replay['records'])!=['p1','p2','p3']
        or replay['records'][0]['instructions']!=8893 or replay['records'][0]['cycles']!=95450):
        raise ValueError('corrected 30-cycle actual GPU replay differs')
    rows.append(dict(name='修复后 30 拍 GPU 的三个真实内核回放',status='P1/P2/P3 代表用例完整输出一致；不是全量验收',
        note='实际宏和物理适配器运行，保留背压断言；修复主机响应握手并使用正确 DCR 读取参数。P1 为 8,893 条指令、95,450 周期。旧错误高低字合成的巨量计数不可使用；仍需三类计数核对、1000 条覆盖、新布局布线和功耗。'))
    synth=data['gpu_repaired_synthesis'];probe=data['gpu_repaired_counter_probe'];tag=data['cpu_tag_register_proof']
    if (synth['status']!='RETIMED_GPU_SYNTHESIS_STAGE_PASS' or synth['macro_count']!=37 or synth['clock_period_ns']!=10
        or probe['status']!='REPAIRED_GPU_COUNTER_COLLECTION_STAGE_PASS' or probe['ordinals']!=[0,330,660]
        or len(probe['records'])!=3 or probe['performance_eligible'] is not False
        or tag['status']!='CPU_TAG_REGISTER_MAPPING_STAGE_PASS' or tag['differential_records']!=15360
        or tag['seeds']!=list(range(1,11)) or tag['macro_count']!=29 or tag['tag_register_bits']!=11296):
        raise ValueError('repaired GPU counters/synthesis or CPU tag proof differs')
    rows.append(dict(name='GPU 修复后综合与三类计数核对',status='37 宏综合通过；新候选 3/1000 条记录、每条 3 类计数通过',
        note='P1/P2/P3 seed=1 的周期分别为 95,450／102,663／193,798；指令为 8,893／9,659／18,818。每次单独进程执行并比较完整输出，DMA/cache 字节取自实际配置的 RTL 计数，未用主机时间补值。布局、全量计数和物理功耗未通过前仍不具备性能计分资格。'))
    rows.append(dict(name='CPU 半周期标签路径的独立候选',status='10 seed、15,360 条逐值比对及结构检查通过；尚非整机通过',
        note='只把 512×22 位标签存储换成真实可综合寄存器，保留容量、原 ROM 和顶层写优先旁路，其余 29 个 SRAM 不变。原宏输出在下降沿后出现，新标签输出提前到上升沿后；整机总线、输出与计数必须再次逐周期验证。面积、功耗和最终时序重新测量，不计一次学生晋升。'))
    whole=data['cpu_tag_whole'];resource=data['cpu_tag_whole_resource']
    if (whole['status']!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS'
        or whole['transcript_join']['baseline_records']!=1000 or not whole['transcript_join']['native_completion']
        or resource['status']!='PASS' or not resource['limits_enforced'] or resource['memory_peak_bytes']>8*1024**3):
        raise ValueError('cache-tag whole replay/resource qualification differs')
    rows.append(dict(name='CPU 标签寄存器候选的完整整机回放',status='1000 条 baseline、原 Nano、DFI/UART 和硬件计数一致',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='实际运行 102,392,157 周期，2 vCPU / 8 GiB 限制生效，峰值约 4.50 GiB。29 个真实 SRAM 与真实标签寄存器均参与执行；新综合、100 MHz 时序、布线与功耗尚待验证，最终选中 PTQ 模型也须在最终硬件上重放。'))
    placement=data['gpu_repaired_placement_hold'];unit=data['gpu_nrm_differential']
    if (placement['status']!='HOLD' or placement['preflight_complete'] is not False or not placement['macro_power_connected']
        or not placement['reason'].startswith('TimeoutExpired:')
        or "'do-3_3_place_gp']' timed out after 600 seconds" not in placement['reason']
        or unit['status']!='FPU_NRM_CUT_DIFFERENTIAL_STAGE_PASS' or unit['latency_before']!=17
        or unit['latency_after']!=31 or unit['records']!=35243 or set(unit['seeds'])!={str(i) for i in range(1,11)}):
        raise ValueError('GPU timed-out placement or new normalization differential differs')
    rows.append(dict(name='GPU 30 拍候选的物理预检',status='HOLD：全局布局阶段 600 秒超时；未进入详细布局或 route',
        note='37 个 SRAM 的 74 个电源引脚已核对连接。保存的中间全局布局 STA 最差裕量约 −5.26 ns，路径为浮点归一化的移位、舍入与打包组合链；这不是最终详细布局结果，也不能作为物理 PASS。1000 条新版性能采集因预检失败未启动。'))
    rows.append(dict(name='GPU 31 拍归一化切分候选',status='10 seed、35,243 条完整输出位与异常标志差分通过',
        note='仅在归一化移位和舍入之间增加寄存器，并同步元数据与 valid；未改精度、数值或原始算术。该局部结果不等于完整 GPU 通过；须重新导出、映射真实 SRAM、保留全部接口修复、整机回放并重做物理证据。旧计数一律不复用。'))
    placement=data['cpu_tag_placement_hold'];bank=data['cpu_tag_bank_proof']
    if (placement['status']!='HOLD' or placement['placement_wns_ns']>=0 or not placement['macro_power_connected']
        or bank['status']!='CPU_TAG_BANK_MAPPING_STAGE_PASS' or bank['tag_register_bits']!=11621
        or bank['differential_records']!=15360 or bank['macro_count']!=29):
        raise ValueError('CPU tag placement/banked proof stages differ')
    rows.append(dict(name='CPU 标签寄存器方案的最终详细布局',status='HOLD：WNS −2.27692 ns；布线入口拒绝启动',
        placement_wns_ns=placement['placement_wns_ns'],
        note='最终最差路径由仲裁信号穿过 512 项标签读选择树到标签输出寄存器，不是中间全局布局报告中的 ROM 路径。下一候选只把标签读输出分成 16 组寄存；保持全部存储容量、一拍读延迟和顶层写优先旁路。'))
    rows.append(dict(name='CPU 标签读输出 16 组寄存候选',status='10 seed、15,360 条完整值对照及 11,621 位寄存器结构通过',
        note='真实标签存储为 512×22 位，另有 16×22 位读寄存器和 5 位选择器，保留 29 个 SRAM。局部测试覆盖所有标签地址、写掩码及停顿；整机回归和新物理结果尚未闭合，不计学生优化晋升。'))
    whole=data['gpu_nrm_whole'];resource=data['gpu_nrm_whole_resource']
    if (whole['status']!='PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS'
        or sorted(row['operator'] for row in whole['records'])!=['p1','p2','p3']
        or whole['all_case_coverage'] is not False or whole['performance_eligible'] is not False
        or resource['status']!='PASS' or not resource['limits_enforced'] or resource['memory_peak_bytes']>8*1024**3):
        raise ValueError('31-cycle whole representative replay is not qualified')
    rows.append(dict(name='GPU 31 拍归一化候选的完整边界回放',status='三个实际内核的全部输出一致；重新综合／布局仍待完成',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='37 个真实 SRAM、DCR 响应和正确端口顺序均在实际执行路径中。2 vCPU / 8 GiB 限制生效，峰值约 0.92 GiB；编译缓存可能影响该次峰值，不能替代干净环境首次构建测量。这仍是三个代表用例，不冒充 1000 条覆盖或正式物理验收。'))
    whole=data['cpu_tag_bank_whole'];resource=data['cpu_tag_bank_whole_resource']
    if (whole['status']!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS'
        or whole['transcript_join']['baseline_records']!=1000 or not whole['transcript_join']['native_completion']
        or whole['formal_baseline'] is not False or resource['status']!='PASS'
        or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3):
        raise ValueError('banked-tag CPU whole replay/resource qualification differs')
    rows.append(dict(name='CPU 16 组标签读寄存器候选的整机回放',status='1000 条输出和硬件计数匹配；新综合／布局待完成',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='在 2 vCPU / 8 GiB 限制下运行，峰值约 4.56 GiB。保留全部 ROM 字节、29 个真实 SRAM 及标签对外一拍读延迟；回放的旧模型状态一致。最终选中 PTQ 模型、暖复位、完整协议及 100 MHz 物理验收仍是独立门，不能据此发行 baseline。'))
    cpu_synth=data['cpu_tag_bank_synthesis'];gpu_synth=data['gpu_nrm_synthesis'];probe=data['gpu_nrm_counters']
    if (cpu_synth['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS'
        or gpu_synth['status']!='RETIMED_GPU_SYNTHESIS_STAGE_PASS' or gpu_synth['macro_count']!=37
        or probe['status']!='REPAIRED_GPU_COUNTER_COLLECTION_STAGE_PASS' or probe['ordinals']!=[0,330,660]
        or len(probe['records'])!=3 or probe['performance_eligible'] is not False):
        raise ValueError('new CPU/GPU synthesis or independent counter probe differs')
    rows.append(dict(name='最新 CPU／GPU 候选综合与计数预检',status='两份新综合通过；GPU 新版三个算子的独立 0/4/7 类计数通过',
        note='CPU 使用 16 组标签读寄存器；GPU 使用 31 拍算术及全部接口修复。此处不引用旧 RTL 计数，不把三个代表用例当成全量覆盖。两平台仍须通过布局、布线、活动功耗和协议验收；只有同一边界的单次采集对照与布局预检均通过，才启动新的全 1000 条硬件计数。'))
    cpu=data['cpu_tag_bank_placement_hold'];gpu=data['gpu_nrm_placement_hold'];audit=data['gpu_iteration_hold'];proof=data['gpu_sign_differential']
    if (cpu['status']!='HOLD' or cpu['placement_wns_ns']>=0 or cpu['macro_power_connected'] is not True
        or gpu['status']!='HOLD' or gpu['macro_power_connected'] is not True
        or audit['status']!='HOLD_INTERMEDIATE_SINGLE_ITERATION_SETUP' or audit['placement_completed'] is not False
        or proof['status']!='FPU_SIGN_CUT_DIFFERENTIAL_STAGE_PASS' or proof['latency_after']!=57
        or proof['records']<=30000 or sorted(map(int,proof['seeds']))!=list(range(1,11))):
        raise ValueError('latest physical HOLD and NR sign differential differ')
    rows.append(dict(name='CPU 分组标签候选最终详细布局',status='HOLD：100 MHz WNS −2.24138 ns；没有启动布线',
        placement_wns_ns=cpu['placement_wns_ns'],
        note='标签读树不再是最差路径；当前路径由 CPU 总线控制经扇出树到程序 ROM 分组读寄存器。全部 1000 条数值/计数回放通过不代表物理通过。最终 PTQ 复验的前置门也保持关闭，旧模型会话不得冒充此版 CPU 验收。'))
    rows.append(dict(name='GPU 31 拍候选布局与后续 57 拍局部恢复',status='31 拍布局报告阶段超时 HOLD；57 拍局部 35,049 条结果及标志一致',
        intermediate_report_slack_ns=audit['reported_slack_ns'],
        note='中间 STA 约 −2.32 ns，属于相邻迭代级的符号判定到更新链，不是最终布局签核。未启动该版布线或 1000 条正式计数。下一私有候选仅将每次迭代的判定与更新分两拍，保留算法/精度/舍入；35,049 条、10 seed 对照已通过，整机和新物理证据仍待完成。'))
    whole=data['gpu_sign_whole'];synth=data['gpu_sign_synthesis'];local=data['cpu_request_local']
    if (whole['status']!='PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS'
        or sorted(r['operator'] for r in whole['records'])!=['p1','p2','p3']
        or whole['all_case_coverage'] is not False or synth['status']!='RETIMED_GPU_SYNTHESIS_STAGE_PASS'
        or synth['macro_count']!=37 or synth['clock_period_ns']!=10
        or local['status']!='CPU_ROM_REQUEST_LOCAL_PROOF_STAGE_PASS'
        or local['real_rom']['records']!=37888
        or local['mutations_killed']!=['wrong-address','early-ack','ignore-cancel','ignore-reset']):
        raise ValueError('57-cycle GPU whole/synthesis or CPU local request proof differs')
    rows.append(dict(name='GPU 57 拍候选的整机代表回放与新综合',status='三个内核全部输出一致；37 个真实 SRAM 综合通过，布局尚待完成',
        note='独立于 31 拍版本重新编译和执行，不复用旧版计数。只有新的布局预检通过才启动布线；代表回放不等于全 1000 条覆盖，也不等于协议、功耗或正式 baseline 通过。'))
    rows.append(dict(name='CPU 两周期 ROM 请求边界的局部证明',status='37,888 次真实 ROM 逐字比较通过；四种故障变体全部被识别',
        note='覆盖全部 32,768 个地址及 seed 1–10 的 5,120 次随机读取，记录完整预期字与实际字；超出已初始化 ROM 的地址仍按未知值检查。补充保持请求跨复位的检查后，错误地址、提前应答、忽略取消和忽略复位均失败。此修复改变真实周期，必须使用自身 SDRAM 模型重跑 1000 条完整记录；不沿用旧计数，不计学生晋升。'))
    whole=data['cpu_independent_whole'];resource=data['cpu_independent_resource']
    if (whole['status']!='CPU_MAPPED_COLD_START_REPLAY_STAGE_PASS'
        or whole.get('independent_external_memory') is not True or whole.get('memory_return_lockstep_checked') is not True
        or whole['transcript_join']['baseline_records']!=1000 or whole['transcript_join']['native_completion'] is not True
        or resource['status']!='PASS' or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3):
        raise ValueError('independent-memory whole CPU qualification differs')
    rows.append(dict(name='CPU 自身请求驱动的独立 SDRAM 回放环境',status='1000 条输出、原 Nano、DFI/UART 与硬件计数全部一致',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='未改 CPU RTL；只将实际 CPU 的内存返回改接到由它自己的 DFI 请求驱动的原始 SDRAM 模型，保留原逐周期检查并增加完整内存返回比较。2 vCPU / 8 GiB 限制生效，峰值约 4.56 GiB。这证明新回放环境可用，不证明两周期 ROM 候选或最终物理通过。'))
    formal=data['cpu_request_formal'];cache=data['gpu_sign_cache_hold'];counter=data['gpu_sign_counter_probe'];multi=data['gpu_sign_multiclass']
    if (formal['status']!='CPU_ROM_REQUEST_BOUNDED_FORMAL_STAGE_PASS' or formal['bounded_steps']!=24
        or len(formal['outcomes'])!=5 or formal['unbounded_proof'] is not False
        or cache['status']!='HOLD_INTERMEDIATE_MSHR_READ_SETUP' or cache['placement_completed'] is not False
        or counter['status']!='REPAIRED_GPU_COUNTER_COLLECTION_STAGE_PASS' or counter['ordinals']!=[0,330,660]
        or multi['status']!='SIGN_MULTICLASS_COMPARISON_STAGE_PASS' or multi['arithmetic_latency']!=57):
        raise ValueError('new local formal or GPU diagnostic evidence differs')
    rows.append(dict(name='CPU 两周期 ROM 的局部有界形式检查',status='24 步任意输入证明通过；四种故障变体全部出现反例',
        note='只证明请求、取消、复位及地址捕获边界。锁定 Yosys 需要先规范化边沿检查，再转换断言；保留两次工具兼容性 HOLD，没有删除或跳过断言。此项不是全 CPU／Wishbone／LiteDRAM 协议通过。'))
    rows.append(dict(name='GPU 57 拍候选的最新物理 HOLD 与计数',status='全局布局报告阶段超时 HOLD；新版代表计数两种采集方式一致',
        intermediate_report_slack_ns=cache['reported_slack_ns'],
        note='中间路径为缓存 MSHR 读选择到提交寄存器，裕量约 −3.88 ns，不是最终详细布局值。旧 600 秒 HOLD 保留；诊断重跑仅把这一阶段预算改为 1200 秒，不改硬件、时钟或资源。该版完整 1000 条计数与布线均因前置 HOLD 未启动；三个代表用例不能冒充全量验收。'))
    whole=data['cpu_request_whole'];resource=data['cpu_request_recheck_resource'];results=data['cpu_request_results']
    if (whole['status']!='CPU_LATENCY_CHANGED_COLD_START_REPLAY_STAGE_PASS'
        or whole['transcript_join']['baseline_records']!=1000 or whole['cycle_equivalence'] is not False
        or whole['independent_external_memory'] is not True or resource['status']!='PASS'
        or resource['memory_peak_bytes']>8*1024**3 or results['numeric_matches']!=1000
        or results['counts']!={'PASS':0,'FAIL':0,'HOLD':1000}):
        raise ValueError('new-latency CPU complete results/recheck differ')
    rows.append(dict(name='CPU 两周期 ROM 候选的完整实际回放',status='1000 条完整结果及原 Nano 状态一致；新计数已进入 case/seed 浏览器',
        memory_peak_bytes=resource['memory_peak_bytes'],
        note='实际完整运行 109,260,632 周期；原参考为 102,392,157。原 Nano 会话周期 12,098,269 → 12,596,031，约增加 4.1%；指令与 I/D/DMA 字节不变。修正仅针对旧比较器把 Nano 计数误当作不变量的问题：复核同一不可变日志，没有重跑或改写实际输出。新布局、功耗、完整协议和最终选中模型尚未通过，1000 条仍为 HOLD，不计晋升。'))
    retry=data['gpu_report_retry_hold'];resource=data['gpu_report_retry_resource']
    if (retry['status']!='HOLD' or retry['preflight_complete'] is not False
        or retry['macro_power_connected'] is not True or retry['clock_period_ns']!=10
        or "'do-3_5_place_dp']' timed out after 600 seconds" not in retry['reason']
        or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3):
        raise ValueError('GPU detail timeout/resource evidence differs')
    rows.append(dict(name='GPU 同硬件延长报告预算后的详细布局',status='全局布局及尺寸修复完成；详细布局 600 秒超时 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='全局布局与报告耗时约 668 秒，超过原 600 秒预算；1200 秒重跑已完成该阶段。详细布局在第二轮合法化仍有位置冲突，尚未输出最终 WNS。尺寸修复中间路径转到整数乘法，裕量约 −3.83 ns，不是最终签核。37 个宏电源连接保持；峰值约 4.90 GiB、无 OOM。保留原 HOLD，下一次仅从已完成的尺寸修复检查点续跑详细布局，不重复综合或全局布局。'))
    retry=data['gpu_detail_retry_hold'];resource=data['gpu_detail_retry_resource'];pressure=data['gpu_legalizer_pressure']
    if (retry['status']!='HOLD' or 'placement_wns_ns' in retry or retry['preflight_complete'] is not False
        or "'do-3_5_place_dp']' timed out after 1800 seconds" not in retry['reason']
        or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3
        or pressure['status']!='HOLD_UNRESOLVED_LEGALIZATION'
        or data['cpu_request_synthesis']['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS'):
        raise ValueError('new synthesis or unresolved GPU legality differs')
    rows.append(dict(name='CPU 新请求边界综合与 GPU 合法化阻碍',status='CPU 新综合通过；GPU 详细布局 1800 秒仍 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='CPU 的两周期 ROM 版本已通过真实 SRAM 综合，正在推进布局。GPU 原样续跑 1400 次迭代仍有 699 个非法单元，并报告 619 处边缘间距和 108 处 padding 违规，随后整理阶段达到 1800 秒上限。该阶段峰值约 3.42 GiB、无 OOM；工具报告合法化利用率 82.9%，不能误读为配置目标密度 25%。下一项只对照同工具版本的 diamond 合法化器，不改变 RTL、芯片面积、宏位置、时钟或门槛；这不是时序通过。'))
    place=data['cpu_read_buffer_place'];route=data['cpu_read_buffer_route'];stop=data['cpu_negative_cts_stop']
    resource=data['cpu_read_buffer_route_resource'];diamond=data['gpu_diamond_hold'];mult=data['gpu_multiplier_local']
    if (place['status']!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS' or place['placement_wns_ns']<0
        or place.get('one_buffer_topology_checked') is not True or route['status']!='HOLD'
        or stop['wns_ns']>=0 or stop['clock_period_ns']!=10 or resource['limits_enforced'] is not True
        or resource['memory_peak_bytes']>8*1024**3 or diamond['status']!='HOLD'
        or mult['status']!='GPU_MULTIPLIER_LOCAL_DIFFERENTIAL_STAGE_PASS'
        or mult['records']!=43211 or mult['mutants_killed']!=4 or mult['adopted_into_gpu'] is not False):
        raise ValueError('CPU CTS HOLD or GPU local differential evidence differs')
    rows.append(dict(name='CPU 单缓冲布局通过，但时钟树后失败',status='布局 +0.0548 ns；CTS −1.92968 ns，布线停止并保留 HOLD',
        placement_wns_ns=place['placement_wns_ns'],cts_wns_ns=stop['wns_ns'],
        note='最差路径从 SRAM 读出到外部 DFI 写数据端口：时钟树延迟约 3.36 ns，数据 11.43 ns 到达，要求 9.50 ns。寄存器间最差路径仍勉强通过。已仅终止本次所属的布线生产进程，由其清理工具子进程并自行写出 HOLD；未改约束、频率或旧结果。下一项是命令、数据、使能共同经过 DFI 输出寄存器，必须重新验证整机和真实计数，不能把布局通过当成物理闭合。'))
    rows.append(dict(name='GPU 合法化与整数乘法局部验证',status='diamond 合法化仍 HOLD；43,211 条完整 66-bit 乘法对照通过',
        note='同一检查点改用 diamond 合法化器后报告 635 个实例无法放置，未产生合格最终 WNS。整数乘法候选保持 3 个使能时钟延迟；10 seed、原 RTL／独立整数 golden／候选完整位结果一致，32,460 次 stall 保持检查通过，四种故障变体全部识别。候选尚未接入 GPU，不是整机证明或物理 PASS。'))
    failed=data['cpu_dfi_failed_replay'];stopped=data['cpu_dfi_failure_stop'];aligned=data['cpu_dfi_aligned_mapping']
    exported=data['gpu_multiplier_export']
    if (failed['status']!='HOLD' or stopped['status']!='ACTUAL_NANO_FAILURE_STOP_REQUESTED'
        or 'status=-1 count=0' not in stopped['witness']
        or aligned['status']!='CPU_DFI_OUTPUT_MAPPING_STAGE_PASS' or aligned['native_read_valid_added_cycles']!=1
        or aligned['macro_count']!=29 or aligned['local_formal_steps']!=24
        or exported['status']!='GPU_MULTIPLIER_SOURCE_EXPORT_STAGE_PASS'
        or exported['integer_multiplier_latency']!=3):
        raise ValueError('DFI failed whole replay/alignment or multiplier export differs')
    rows.append(dict(name='CPU DFI 输出候选：整机失败暴露读返回对齐问题',status='只延迟输出的版本 HOLD；三条读有效链补齐候选通过局部映射，完整回放尚待完成',
        note='前一候选局部 169 位寄存器证明通过，但真实整机正常用例返回输入错误，Nano status=-1/count=0；已停止并保留原始日志，后续综合／布线没有放行。生成控制器的三个读返回有效信号使用固定五拍链，不能只延迟外部请求。新候选同步增加一拍，保留 29 个 SRAM、相同接口和数值合同；额外三位有效信号通过 24 步局部检查。这不是整机协议证明。完整回放改为逐条比较真实 UART，错误立即停止；参考值不驱动硬件。'))
    rows.append(dict(name='GPU 三周期乘法候选进入独立整机源码',status='57 拍除法／开方配置不变，新乘法器全芯片源码导出通过',
        note='私有源码副本保留 1 core / 2 warps / 4 threads、缓存和宏几何，原厂仓库及旧候选不修改。只采用已通过完整位差分的三周期乘法拆分，随后重新映射 SRAM、重建接口修复并运行三个真实内核。当前还不是新整机回放通过，更不是物理或正式 baseline 通过；旧计数不能复用。'))
    whole=data['cpu_dfi_aligned_replay'];resource=data['cpu_dfi_aligned_resource'];report=data['cpu_dfi_aligned_results']
    if (whole['status']!='CPU_DFI_OUTPUT_COLD_START_REPLAY_STAGE_PASS'
        or whole['transcript_join']['baseline_records']!=1000 or whole['transcript_join']['native_completion'] is not True
        or report['numeric_matches']!=1000 or report['counts']!={'PASS':0,'FAIL':0,'HOLD':1000}
        or resource['status']!='PASS' or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3
        or data['cpu_dfi_aligned_synthesis']['status']!='CPU_SYNTHESIS_PREFLIGHT_STAGE_PASS'):
        raise ValueError('aligned DFI full replay, raw results or synthesis differs')
    rows.append(dict(name='CPU DFI 与读返回共同对齐后的完整回放',status='1000 条完整输出及原 Nano 状态一致；新综合通过，物理签核仍待完成',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='本轮真实重新执行，逐条 UART 检查和最终全量比较均通过；报告已切换到这版硬件的全部新计数，原始日志保留。2 vCPU / 8 GiB 限制生效，峰值约 6.36 GiB、无 OOM。原 Nano 实测 12,601,854 周期，比上一版两周期 ROM 候选多 5,823 周期；指令和流量不变，是可实现性代价，不记晋升。仍须完成最终选中 PTQ 模型、完整协议、新版布局／布线和负载功耗，1000 条保持正式 HOLD。'))
    placement=data['cpu_dfi_aligned_placement'];whole=data['gpu_multiplier_whole'];resource=data['gpu_multiplier_whole_resource']
    if (placement['status']!='HOLD' or placement.get('placement_wns_ns',0)>=0
        or placement['clock_period_ns']!=10 or placement['macro_power_connected'] is not True
        or whole['status']!='GPU_MULTIPLIER_REPRESENTATIVE_REPLAY_STAGE_PASS'
        or whole['integer_multiplier_latency']!=3 or whole['arithmetic_latency']!=57
        or resource['status']!='PASS' or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3):
        raise ValueError('DFI placement HOLD or new multiplier whole replay differs')
    rows.append(dict(name='CPU 新 DFI 完整回放后的布局时序阻碍',status='详细布局 −1.69675 ns，维持 HOLD，未进入布线',
        placement_wns_ns=placement['placement_wns_ns'],
        note='最差路径位于 VexRiscv 整数乘法器，末级 a21boi_0 单元延迟约 1.70 ns、输出转换约 2.28 ns；不能以功能 1000 条通过代替时序签核。下一项先比较同逻辑单元的驱动能力，以区分局部负载与乘法组合链深度；不改频率、时序约束或已保存证据。'))
    rows.append(dict(name='GPU 新三周期乘法器的实际整机代表回放',status='P1/P2/P3 三个真实内核完整输出通过；准备新综合／布局',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='新源码独立完成 SRAM 映射、接口修复、RTL 编译和三个内核回放；整数乘法仍为三个使能周期，除法／开方仍为 57 拍。资源限制 2 vCPU / 8 GiB 生效。代表测试不等于全 1000 条计数、完整协议、布局布线或负载功耗验收；旧物理证据和计数不复用。'))
    drive=data['cpu_multiplier_drive_audit'];synth=data['gpu_multiplier_synthesis'];place=data['gpu_multiplier_place_hold']
    counters=data['gpu_multiplier_counters'];multi=data['gpu_multiplier_multiclass'];resource=data['gpu_multiplier_physical_resource']
    if (drive['status']!='CPU_DRIVE_DIAGNOSTIC_PARSED' or drive['hardware_adopted'] is not False
        or drive['one_cell_upsizing_closes_timing'] is not False
        or synth['status']!='RETIMED_GPU_SYNTHESIS_STAGE_PASS' or synth['macro_count']!=37
        or place['status']!='HOLD' or "'do-3_3_place_gp']' timed out after 600 seconds" not in place['reason']
        or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3
        or counters['status']!='REPAIRED_GPU_COUNTER_COLLECTION_STAGE_PASS' or counters['ordinals']!=[0,330,660]
        or multi['status']!='SIGN_MULTICLASS_COMPARISON_STAGE_PASS'
        or data['gpu_multiplier_full_hold']['status']!='HOLD'
        or data['gpu_multiplier_full_hold']['reason']!='ValueError: prerequisite HOLD; full counters not started'):
        raise ValueError('drive diagnostic, new GPU counters or blocked physical chain differs')
    rows.append(dict(name='CPU 乘法器的同布局驱动对照',status='单门增强将 −1.696749 ns 改善至 −0.354790 ns，仍未通过',
        note='四种驱动的原始最差裕量依次为 −1.696749／−1.048647／−0.622914／−0.354790 ns。逻辑函数和连接相同，未写回布局或网表；只证明小驱动确实贡献了部分延迟，单门修改不足以闭合。工具命令和 max-slack 格式两次诊断 HOLD 均保留，最终从同一不可变日志重新解析，没有改实际结果。这不是已合法化／布线的物理包。'))
    rows.append(dict(name='GPU 新乘法器综合、计数与布局报告 HOLD',status='37 宏新综合及三类实际计数交叉校验通过；全量计数被布局 HOLD 拦下',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='P1/P2/P3 代表周期分别为 95,450／102,663／193,798，指令、DMA 和 cache 流量也由新 RTL 重测；两种采集方式一致，不能据代表用例领取全量通过或提速分。新综合约 994 秒；全局布局计算约 488 秒，随后在报告阶段触及 600 秒上限，无合格最终 WNS。2 vCPU／8 GiB 限制生效，整段峰值约 6.97 GiB。正式 1000 条计数未启动，下一轮仅延长这一阶段观察预算，原 HOLD 永久保留。'))
    components=data['numeric_path_components'];resource=data['numeric_path_resource'];two=data['cpu_two_gate_diagnostic'];gpu=data['gpu_multiplier_detail_hold']
    if (components['status']!='NUMERIC_PATH_COMPONENT_STAGE_PASS' or len(components['records'])!=510
        or any(r['status']!='PASS' for r in components['records']) or components['whole_operator_pass'] is not False
        or resource['status']!='PASS' or resource['limits_enforced'] is not True
        or two['status']!='CPU_MULTIPLIER_DRIVE_DIAGNOSTIC_COMPLETE' or two['diagnostic_only'] is not True
        or two['worst_slack_ns_by_strength']['4']<=0 or gpu['status']!='HOLD'
        or "'do-3_5_place_dp']' timed out after 600 seconds" not in gpu['reason']):
        raise ValueError('approved numeric component coverage or latest physical diagnostics differ')
    rows.append(dict(name='经确认的数值路径归属与 510 条真实 RTL 见证',status='保留全部原始 case／seed／golden；180 条附加见证及 330 条 BF16 定向组件检查通过',
        note='2026-10-08 用户确认：P1/P2 验证 BF16-RNE；P3／公共数值单元承担 INT8 重量化及饱和。使用独立补充合同，不修改冻结 SPEC 或历史 HOLD。新组件运行输入只有操作数，不含预期答案；正负半值、奇偶舍入、scale 两端、seed 1–10 与响应保持均记录。组件证据不替代 CPU/GPU／整算子、物理、Nano 或整包验收。'))
    rows.append(dict(name='最新 CPU 双门诊断与 GPU 详细布局阻碍',status='CPU 检查点试测 +0.031537 ns；GPU 越过报告阶段，详细布局 600 秒仍 HOLD',
        note='CPU 在同一布局上依次只改变一个门的驱动，复现 −1.696749 与 −0.354790 ns 对照，再得到 −0.083910 与 +0.031537 ns；没有写回 ODB，尚未合法化、布线或验证功耗，不能计物理 PASS。GPU 延长全局布局／报告预算后完成该阶段及尺寸修复，随后详细布局超时，仍无合格最终 WNS。'))
    eco=data['cpu_three_gate_eco'];old_eco=data['cpu_two_gate_eco_hold'];resource=data['cpu_three_gate_eco_resource']
    initial=data['gpu_initial_difference'];exported=data['gpu_initial_export']
    if (eco['status']!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS' or eco['placement_wns_ns']<0
        or eco['macro_power_connected'] is not True or resource['status']!='PASS'
        or old_eco['status']!='HOLD' or 'legalized CPU ECO fails 100 MHz' not in old_eco['reason']
        or initial['status']!='FPU_INITIAL_DIFFERENCE_STAGE_PASS' or initial['records']!=35049
        or initial['latency_after']!=57 or exported['status']!='GPU_MULTIPLIER_SOURCE_EXPORT_STAGE_PASS'):
        raise ValueError('legalized CPU ECO or exact GPU initializer evidence differs')
    rows.append(dict(name='CPU 等价门驱动修复已完成实际合法化',status='三门 ECO 布局 WNS +0.005943 ns；29 宏实际供电检查通过',
        placement_wns_ns=eco['placement_wns_ns'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='双门诊断的正裕量在合法化后变为 −0.009234 ns，原 HOLD 保留；再只增强新关键路径的一个 NAND 驱动，保持精度、时钟和逻辑连接。新候选写出独立 ODB／网表／SDC，并在 2 核／8 GiB 限制下通过布局门。仍须 CTS、布线、功耗与完整协议，不是完整物理包。'))
    rows.append(dict(name='GPU 初始化级比较与减法的精确逻辑修复',status='35,049 条真实 RTL 逐位及异常标志对照通过；新整核源码导出完成',
        note='旧候选尺寸修复后的最差路径从 pre_reg 到 ini_reg，约 −3.130 ns。将比较→选择→减法改为一次扩位减法产生借位和差值，再选择结果；完整位宽、舍入、57 拍除法／开方和三拍乘法延迟不变。10 seed、两种操作和五种舍入模式均对照原 RTL，不复用旧全量计数或物理结果。整核回放及新物理流程仍须完成。'))
    route=data['cpu_eco_grt_hold'];resource=data['cpu_eco_grt_resource'];congestion=data['cpu_congestion_snapshot']
    if (route['status']!='HOLD' or "'do-5_1_grt']' timed out after 1800 seconds" not in route['reason']
        or resource['limits_enforced'] is not True or resource['status']!='HOLD'
        or congestion['status']!='DIAGNOSTIC_CONGESTION_SNAPSHOT' or congestion['route_completed'] is not False):
        raise ValueError('CPU route HOLD or actual congestion snapshot differs')
    rows.append(dict(name='CPU 等价驱动修复后的全局布线阻碍',status='CTS 后进入全局布线，1800 秒拥塞超时；未生成完整物理 PASS',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='已保存 CTS 数据库、全局布线日志及独立拥塞快照。快照报告 20,000 个拥塞条目，其中 15,589 个容量为零；这是工具报告的条目，不宣称覆盖全部布线边。下一步用真实宏位置和电源线投影检查空间关联，再做单变量实验。没有降低频率、减少用例或以延长超时冒充问题解决。'))
    selected=data['cpu_selected_eco_full'];resource=data['cpu_selected_eco_resource'];spatial=data['cpu_congestion_geometry']
    gpu=data['gpu_initial_whole_recovery'];gpu_resource=data['gpu_initial_whole_resource']
    if (selected['status']!='SELECTED_MAPPED_CPU_NUMERICAL_STAGE_PASS' or selected['baseline_records']!=1000
        or len(selected['native_join']['records'])!=11 or selected['accepted_nano_session'] is not False
        or selected['native_join']['token_sha256']!='420033bddbc7de6532338a433a8bd07d50a683ba8c4322245012e254dbe60aac'
        or resource['status']!='PASS' or resource['limits_enforced'] is not True
        or spatial['status']!='DIAGNOSTIC_GEOMETRY_OBSERVED'
        or gpu['status']!='GPU_MULTIPLIER_REPRESENTATIVE_REPLAY_STAGE_PASS'
        or gpu_resource['status']!='PASS' or gpu_resource['limits_enforced'] is not True):
        raise ValueError('new actual selected CPU, spatial observation or initializer GPU replay differs')
    rows.append(dict(name='最终 PTQ 模型在 DFI 对齐 CPU 上重新完成执行',status='1000 条 baseline 与 11 个 Nano token／hidden／logits 完整比对通过，整体验收仍 HOLD',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='中断任务保留为未完成；新独立任务在 2 vCPU／8 GiB 下重新执行并核验 SHA，无 OOM。Nano 实测 12,580,787 周期、7,845,041 条指令，首 token 4,300,109 周期；这些计数绑定最终 PTQ 模型，不能与不同模型直接计提速。仍缺完整复位／协议、布线和负载功耗，不宣称正式 Nano 或 baseline PASS。'))
    rows.append(dict(name='CPU 全局布线拥塞的真实位置核对',status='15,589 个零容量条目中，15,526 个位于 SRAM 宏内部',
        note='只读实际 CTS 数据库和冻结拥塞快照，29 个宏及电源线几何均从 OpenDB 取得。报告没有层信息；空间重合支持宏相关布线受限，但不证明某一项就是唯一根因。候选实验以同一综合和原始布局配方为对照，只把宏间距 80 改为 160 μm；不自动搬用旧布局的三门 ECO，不改 RTL、精度或 100 MHz。'))
    rows.append(dict(name='GPU 精确初始化修复后的新整机代表回放',status='P1/P2/P3 三个真实内核输出通过；旧计数不复用',
        seconds=gpu_resource['elapsed_seconds'],memory_peak_bytes=gpu_resource['memory_peak_bytes'],
        note='中断后的新任务重新完成 SRAM 映射、接口修复、编译和实际内核执行。任务耗时包含串行队列等待。代表回放不等于全 1000 条计数、完整协议、时序和物理通过，后续物理门仍严格独立。'))
    cpu=data['cpu_channel160_hold'];resource=data['cpu_channel160_resource']
    gpu=data['gpu_initial_place_hold'];gpu_resource=data['gpu_initial_place_resource']
    if (cpu['status']!='HOLD' or cpu['geometry']['gap']!=160 or cpu['clock_period_ns']!=10
        or abs(cpu['placement_wns_ns']-(-.730841))>.000001
        or resource['limits_enforced'] is not True or resource['memory_peak_bytes']>8*1024**3
        or gpu['status']!='HOLD' or '100 MHz resized placement fails: -1.70508' not in gpu['reason']
        or gpu_resource['limits_enforced'] is not True or gpu_resource['memory_peak_bytes']>8*1024**3):
        raise ValueError('latest single-variable actual placement HOLD differs')
    rows.append(dict(name='CPU 宏通道加宽后的同网表布局对照',status='80→160 μm；WNS 从 −1.69675 改善为 −0.730841 ns，仍 HOLD',
        placement_wns_ns=cpu['placement_wns_ns'],seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='同一综合、29 宏、100 MHz、原精度和布局配方；按间距推导版图边界，未套用旧三门 ECO。峰值约 2.56 GiB，无 OOM；耗时含队列。新最差路径位于 ROM 地址译码，o21ai_0 单门约 2.35 ns。尚未进入布线，不能宣称拥塞已解决；下一步只试这个门的等价驱动强度。'))
    rows.append(dict(name='GPU 精确初始化修复后的实际布局结果',status='尺寸修复后 −1.70508 ns，早停 HOLD；未执行详细布局与布线',
        seconds=gpu_resource['elapsed_seconds'],memory_peak_bytes=gpu_resource['memory_peak_bytes'],
        note='最差路径转为指令缓存 tag SRAM 到 data SRAM 地址的半周期路径；不是原 FPU 初始化链。实际放置报告显示请求密度 25% 无法容纳标准单元，工具自动提高到约 67%，拥塞膨胀阶段还会更高。下轮仅扩大版图 4200→6000 μm，保持宏位置、网表、密度配置和时钟；扩大版图不保证时序通过。'))
    for key,label in [('student_doctor_a','A 路线功能'),('student_doctor_b_physical','B 路线物理工具')]:
        doctor=data[key]
        if (doctor['status']!='SCOPED_PREFLIGHT_PASS' or doctor['failed_checks']
            or doctor['environment_qualified'] is not False or doctor['release_qualified'] is not False
            or doctor['doctor_source_sha256']!=sha(ROOT/'scripts/student_mini_doctor.py')):
            raise ValueError('read-only student preflight differs')
        rows.append(dict(name=label+'只读环境自检',status='已检查项匹配；不等于完整环境或 baseline 验收',
            note='检查 Python 锁定版本及指定工具启动器／载荷 SHA，系统编译器仅报告找到但未完整认证。A 不要求 Vortex，B 使用独立 Verilator 5.050。没有安装软件、调用实体 GPU 或训练。完整运行库、LiteX/Vortex、干净安装和受限资源执行仍须另行验收。'))
    cpu=data['cpu_rom_gate_legalized'];cts=data['cpu_channel_cts_hold'];gpu=data['gpu_6000_hold']
    if (cpu['status']!='CPU_PLACEMENT_PREFLIGHT_STAGE_PASS' or abs(cpu['placement_wns_ns']-.275174)>1e-6
        or cts['status']!='HOLD' or abs(cts['cts_wns_ns']+.130249)>1e-6
        or gpu['status']!='HOLD' or '100 MHz resized placement fails: -1.64444' not in gpu['reason']):
        raise ValueError('latest legal placement/CTS/expanded GPU measurements differ')
    rows.append(dict(name='CPU 宽通道单门修复与真实时钟树',status='布局 +0.275174 ns；CTS −0.130249 ns，布线前 HOLD',
        placement_wns_ns=cpu['placement_wns_ns'],cts_wns_ns=cts['cts_wns_ns'],
        note='原 ROM 单门驱动修复通过合法化。最新失败路径已转为串口 SRAM 到 serial_source_data[7] 的半周期输出，时钟树插入延迟使其超限；ROM reg-to-reg 路径为正。下一单变量只改变 CTS 延迟缓冲插入比例 1→0.5，同时严格检查 setup/hold，不放宽 I/O 约束。尚未验证全局拥塞是否消失。'))
    rows.append(dict(name='GPU 扩大版图的实测对照',status='4200→6000 μm；−1.70508→−1.64444 ns，仍 HOLD',
        seconds=data['gpu_6000_resource']['elapsed_seconds'],memory_peak_bytes=data['gpu_6000_resource']['memory_peak_bytes'],
        note='面积不足改善，但时序仍卡在 icache tag→命中判断→data 地址的半周期路径。原网表与宏位置不变；这不是最终物理包。下一单变量启用现有指令缓存数据延后流水，LATENCY 2→3；容量、37 宏、F32/INT8 精度及全部测试不变，需要重新执行实际 RTL、计数和物理验证。'))
    selected=data['student_p1_ten_seeds'];summary=selected['ten_seed_summary']
    if (selected['status']!='SELECTED_CASE_RTL_STAGE_PASS' or len(selected['records'])!=10
        or sorted(r['seed'] for r in summary['records'])!=list(range(1,11))
        or summary['status']!='PASS' or summary['bit_mismatch_count']!=0 or summary['failed_seeds']):
        raise ValueError('student ten-seed actual replay incomplete')
    rows.append(dict(name='学生入口 P1-MINI-01 的 seed 1–10 实际 RTL',status='10/10 PASS；BF16 bit mismatch=0，MAE/RMSE/逐元素 delta=0',
        cycles=selected['counter_summary']['cycles']['mean'],dma_bytes=selected['counter_summary']['dma_bytes']['mean'],
        note='完整输入、golden、actual、delta、十 seed 均值已保存；每 seed 1495 cycles、308 DMA bytes。仅是一个 case 的学生入口复现，不是 P1 全部用例通过，也不是六个 baseline。计时资源报告含重任务排队，不能用来宣称学生运行耗时或一小时交付。'))
    numerical=data['numeric_coverage_join'];warm=data['cpu_quiescent_warm_reset'];resource=data['cpu_quiescent_warm_resource']
    if (numerical['status']!='NUMERIC_COVERAGE_JOIN_ONLY' or numerical['numerical_layer_pass']!=1000
        or numerical['numerical_layer_fail']!=0 or numerical['whole_operator_pass'] is not False
        or warm['status']!='CPU_QUIESCENT_WARM_RESET_STAGE_PASS' or warm['phase_baseline_records']!=[1000,1000]
        or warm['external_memory_reloaded_at_reset'] is not False or warm['in_flight_reset_qualified'] is not False
        or len(warm['sessions'])!=2 or any(s['token_sha256']!='420033bddbc7de6532338a433a8bd07d50a683ba8c4322245012e254dbe60aac' for s in warm['sessions'])
        or resource['status']!='PASS' or resource['limits_enforced'] is not True):
        raise ValueError('numeric coverage or actual quiescent reset evidence differs')
    rows.append(dict(name='主输出与真实数值路径逐 case／seed 关联',status='1000/1000 数值层比较通过；正式算子验收仍 HOLD',
        note='按完整输入 SHA 将主算子输出、错误状态与 180 条指定 INT8 组件见证关联，并保留 330 条 BF16 定向记录。单 seed 失败不能被均值掩盖。原始 190 条 HOLD 不被改写：其中数值组件归属已明确，但 P2 乱序分块等协议缺项仍待整体验证；此汇总不替代独立 FP32 语义误差报告。'))
    rows.append(dict(name='CPU 真实 ASIC 复位后的完整恢复',status='冷启动及静止边界复位后各 1000 条 baseline、11 个 Nano token 完整比对通过',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='实际复位引脚保持 8 个周期，外部 RAM 不重新灌入；两轮输出、状态、选择结果、hidden、logits 和 token SHA 全部核验。2 vCPU／8 GiB 限制生效，无 OOM。执行途中复位、其他协议、最终布线与功耗仍独立验收，不把这一阶段称为完整 Nano／B0 PASS。'))
    for op in ('p2','p3'):
        selected=data['student_'+op+'_ten_seeds'];summary=selected['ten_seed_summary'];resource=data['student_'+op+'_ten_seeds_resource']
        if (selected['status']!='SELECTED_CASE_RTL_STAGE_PASS' or len(selected['records'])!=10
            or sorted(r['seed'] for r in summary['records'])!=list(range(1,11))
            or summary['status']!='PASS' or summary['bit_mismatch_count']!=0 or summary['failed_seeds']
            or resource['status']!='PASS' or resource['limits_enforced'] is not True):
            raise ValueError('student P2/P3 ten-seed replay incomplete')
        rows.append(dict(name='学生入口 '+op.upper()+'-MINI-01 的 seed 1–10 实际 RTL',status='10/10 PASS；逐元素 delta、bit mismatch、MAE、RMSE 均为零',
            cycles=selected['counter_summary']['cycles']['mean'],dma_bytes=selected['counter_summary']['dma_bytes']['mean'],
            memory_peak_bytes=resource['memory_peak_bytes'],
            note='真实 Verilator 运行，保留完整输入、golden、actual、逐 seed 计数及十 seed 汇总；2 vCPU／8 GiB 内通过，无实体 GPU。仅验证一个最小 case 的学生入口，不能替代全部算子用例、协议或六 baseline 验收。资源耗时含排队，不作为纯执行时间或一小时交付证明。'))
    if abs(data['cpu_cts_derate_hold']['cts_wns_ns']+.130249)>1e-6 or data['cpu_cts_derate_hold']['status']!='HOLD':
        raise ValueError('CTS derate comparison differs')
    rows.append(dict(name='CPU 时钟树插入比例实验无改善',status='比例 1→0.5 后仍 −0.130249 ns；继续 HOLD',
        note='实际命令含新参数，但仍插入 4 个延迟缓冲；锁定源码的新 LatencyBalancer 未读取该比例。保留失败结果。下一变量仅关闭 CTS insertion-delay 平衡；STA 仍计真实延迟，保持 setup/hold、I/O 约束与 100 MHz，不升级工具或降低门槛。'))
    reset=data['cpu_dfi_read_reset'];resource=data['cpu_dfi_read_reset_resource']
    if (reset['status']!='CPU_DFI_READ_RESET_RECOVERY_STAGE_PASS' or reset['phase_baseline_records']!=[1000]
        or reset['dfi_read_interruption_qualified'] is not True or reset['external_memory_reloaded_at_reset'] is not False
        or reset['whole_soc_protocol'] is not False or len(reset['sessions'])!=1
        or reset['sessions'][0]['token_sha256']!='420033bddbc7de6532338a433a8bd07d50a683ba8c4322245012e254dbe60aac'
        or resource['status']!='PASS' or resource['limits_enforced'] is not True):
        raise ValueError('actual CPU DFI read interruption/recovery evidence differs')
    rows.append(dict(name='CPU 执行途中 DFI 读请求复位恢复',status='真实未返回读请求后复位；恢复后 1000 条及 11 个 Nano token 比对通过',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='第 913,623 周期观察到读请求=1、数据响应=0，接收后拉实际 ASIC 复位 8 周期，期间 UART 静默，外部 RAM 保留。恢复后核对完整输出、状态、hidden、logits 与同一 token SHA。首个启动器路径失败被独立保留，修正后重新执行；此结果仅证明一次真实读中断恢复，不代表写中断或整个 Wishbone/LiteDRAM 协议均已通过。'))
    gpu=data['gpu_icache_replay'];actual=data['gpu_icache_actual'];resource=data['gpu_icache_resource']
    if (gpu['status']!='GPU_ICACHE_PIPELINE_REPRESENTATIVE_STAGE_PASS' or gpu['icache_latency_after']!=3
        or gpu['old_counters_reusable'] is not False or actual['status']!='PHYSICAL_BOUNDARY_REPRESENTATIVE_REPLAY_STAGE_PASS'
        or [(r['operator'],r['cycles'],r['instructions']) for r in actual['records']]!=[('p1',104286,8893),('p2',112261,9659),('p3',210963,18818)]
        or resource['status']!='PASS' or resource['limits_enforced'] is not True):
        raise ValueError('actual new cache representative execution differs')
    rows.append(dict(name='GPU 指令缓存流水线 2→3 的实际整机执行',status='三个算子完整输出通过；新物理与全量计数仍独立待验收',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='P1/P2/P3 分别实测 104286/112261/210963 周期及 8893/9659/18818 指令。缓存容量、37 宏、F32/INT8 精度均未减少；仅增加原有缓存数据流水线。P1 比前一版代表用例增加约 9.26% 周期，这是争取可实现性的代价，不是优化晋升，不复用旧硬件计数。耗时包含等待。'))
    cts=data['cpu_cts_no_insertion']
    if cts['status']!='HOLD' or abs(cts['cts_wns_ns']+.423908)>1e-6:
        raise ValueError('CPU no-insertion-delay CTS HOLD differs')
    rows.append(dict(name='CPU 时钟树单变量实验：关闭插入延迟均衡',status='WNS −0.423908 ns，比原 −0.130249 ns 更差；HOLD',
        cts_wns_ns=cts['cts_wns_ns'],
        note='没有修改 10 ns 时钟、I/O 约束或 RTL。此候选在 CTS 预检停止，未进入布线；不能当成拥塞修复。后续诊断从原较好的时钟树数据库出发，逐一核对精确缓冲器及 setup/hold。'))
    regression=data['linux_bound_regression'];resource=data['linux_bound_regression_resource']
    if (regression['status']!='SOURCE_BOUND_REGRESSION_PASS'
        or regression['counts']!=dict(passed=1844,failed=0,errors=0,skipped=12)
        or regression['changed_sources'] or resource['status']!='PASS' or resource['limits_enforced'] is not True):
        raise ValueError('source-stable full Linux regression differs')
    rows.append(dict(name='固定源码快照的 Linux 全量回归',status='1844 通过、12 跳过、0 失败；执行前后源码一致',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='记录 JUnit、原始日志、依赖版本及运行前后 SHA。修复了进度服务在 Linux 上错误使用 Windows 路径转换的问题；跳过项仍逐项保留。该结论只覆盖这次源码快照，后续诊断／页面修改需要重新回归；不等于物理、协议或完整工作包验收。'))
    diagnostic=data['cpu_single_buffer_diagnostic'];resource=data['cpu_single_buffer_resource']
    expected=dict(original=dict(setup_ns=-.130249,hold_ns=.003279),single_buffer_bypassed=dict(setup_ns=.005626,hold_ns=.045087))
    if (diagnostic['status']!='CPU_CTS_BUFFER_DIAGNOSTIC_COMPLETE' or diagnostic['measurements']!=expected
        or diagnostic['next_adoption_eligible'] is not True or diagnostic['physical_evidence_complete'] is not False
        or resource['status']!='PASS' or resource['limits_enforced'] is not True):
        raise ValueError('exact one-buffer setup/hold diagnostic differs')
    rows.append(dict(name='CPU 精确旁路一个时钟缓冲器的实测诊断',status='setup +0.005626 ns，hold +0.045087 ns；可进入新候选，尚未布线通过',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='原 −0.130249 ns 可重复；仅移除 delaybuf_3_core_clock，Liberty 确认非反相、连接检查确认只有一个缓冲器变化，29 个宏不变。诊断只在内存中操作，不覆盖原 CTS 数据库。setup 仅约 5.6 ps 裕量，布线后仍可能失败；未修改时钟、I/O 约束或精度。'))
    synthesis=data['gpu_icache_synthesis_hold'];resource=data['gpu_icache_physical_resource']
    counters=data['gpu_icache_counter_comparison'];regression=data['linux_expanded_source_regression']
    if (synthesis['status']!='HOLD' or not synthesis['reason'].startswith('TimeoutExpired:') or '1800 seconds' not in synthesis['reason']
        or resource['status']!='HOLD' or resource['limits_enforced'] is not True
        or counters['status']!='GPU_ICACHE_REPRESENTATIVE_COUNTERS_STAGE_PASS' or counters['all_case_coverage'] is not False
        or regression['status']!='SOURCE_BOUND_REGRESSION_PASS' or regression['changed_sources']
        or regression['counts']!=dict(passed=1863,failed=0,errors=0,skipped=12)):
        raise ValueError('latest bounded GPU or full regression evidence differs')
    rows.append(dict(name='GPU 新缓存物理预检的真实超时',status='ABC 综合映射达到 1800 秒上限，HOLD；没有进入布局',
        seconds=resource['elapsed_seconds'],memory_peak_bytes=resource['memory_peak_bytes'],
        note='资源记录峰值约 4.15 GiB，OOM 为 0。此来源失败后，对应的全量计数和布线不会绕过预检。下一轮只改为锁定工具自带 ABC_AREA=1 配方，保留 1800 秒、2 vCPU／8 GiB、相同 RTL、6000 μm、10 ns 和全部精度；该实验不保证时序通过，也不是晋升。总耗时含前置等待与来源校验。'))
    rows.append(dict(name='GPU 新缓存多类计数对照',status='三个代表内核：一次执行采集与独立计数采集一致',
        note='使用真实 RTL 与 DCR 查询，并保持原内核、输入镜像和编译 RTL 不变。该阶段通过仅验证计数采集方法及三个代表，all_case_coverage 仍为 false，不能冒充 1000 条计数或正式性能门通过。'))
    rows.append(dict(name='扩展源码类型后的 Linux 全量回归',status='1863 通过、12 跳过、0 失败；前后源码 SHA 一致',
        seconds=regression['execution_seconds'],
        note='快照现在额外包含 .svh/.vh、.mem、.cu 和 .sby，避免 RTL include、查表数据或 GPU 内核变化漏检。原始 JUnit 与跳过原因保留；此快照完成后才新增 CPU 布线入口，并另跑其 6 项测试。阶段回归不等于最终整包验收。'))
    bindings={path:sha(ROOT/path) for path in sources.values()}
    bindings['scripts/student_mini_doctor.py']=sha(ROOT/'scripts/student_mini_doctor.py')
    bindings[Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__))
    identity=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    out=ROOT/'grading/evidence/student-mini-v1/progress'/identity;out.mkdir(parents=True,exist_ok=False)
    path=out/'progress.json'
    path.write_text(json.dumps(dict(status='PARTIAL_NOT_RELEASED',formal_baselines=0,physical_packages=0,raw_physical_bundles_verified=3,
                                   nano_sessions=0,released_archives=0,one_hour_full_delivery_achieved=False,
                                   rows=rows,bindings=bindings),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(path=str(path),sha256=sha(path))))

if __name__=='__main__':main()
