"""Private serial split-order feasibility candidate; arithmetic remains unchanged."""
from pathlib import Path
from scripts.resume_student_mini_interrupted import replace_once

FILES=('p2_split_kv_b4_divider_finalize.sv','p2_split_kv_b4_serial_output.sv','p2_student_mini_vector.sv')


def project(name,source):
    if 'reverse_splits_i' in source:raise ValueError('already projected P2 source')
    if name==FILES[0]:
        changes={
            '  input  logic [31:0]             cache_len_i,':'  input logic reverse_splits_i,\n  input  logic [31:0]             cache_len_i,',
            'IDLE, SCAN, LOCAL_UPDATE, STORE_PARTIAL, BEGIN_MERGE, MERGE,':'IDLE, FIND_REVERSE_START, SCAN, LOCAL_UPDATE, STORE_PARTIAL, BEGIN_MERGE, MERGE,',
            '  logic waiting_q;':'  logic reverse_q;\n  logic waiting_q;',
            "      splits_q <= '0; split_q <= '0; merge_index_q <= '0;":"      reverse_q <= 1'b0;\n      splits_q <= '0; split_q <= '0; merge_index_q <= '0;",
            '          length_q <= cache_len_i;':'          reverse_q <= reverse_splits_i;\n          length_q <= cache_len_i;',
            '            state_q <= SCAN;\n          end\n        end\n        SCAN:':'''            state_q <= reverse_splits_i ? FIND_REVERSE_START : SCAN;
          end
        end
        FIND_REVERSE_START: begin
          // Locate the final nonempty interval serially; no new divider.
          if (split_end_q == length_q) begin
            splits_q <= {1'b0, split_q} + 1'b1;
            token_q <= split_begin_q;
            state_q <= SCAN;
          end else begin
            split_q <= split_q + 1'b1;
            split_begin_q <= split_end_q;
            split_end_q <= (next_split_end_wide > {1'b0, length_q}) ?
                           length_q : next_split_end_wide[31:0];
          end
        end
        SCAN:''',
            '          if (split_end_q == length_q) begin\n            // ceil':'''          if (reverse_q) begin
            if (split_q == 0) state_q <= BEGIN_MERGE;
            else begin
              split_q <= split_q - 1'b1;
              split_end_q <= split_begin_q;
              split_begin_q <= split_begin_q - chunk_q;
              token_q <= split_begin_q - chunk_q;
              local_valid_q <= 1'b0;
              local_max_q <= '0;
              local_sum_q <= '0;
              local_weighted_q <= '0;
              state_q <= SCAN;
            end
          end else if (split_end_q == length_q) begin
            // ceil''',
        }
    elif name==FILES[1]:
        changes={
            '  input  logic [31:0]             cache_len_i,':'  input logic reverse_splits_i,\n  input  logic [31:0]             cache_len_i,',
            '    .cache_len_i, .splits_i, .page_size_i, .value_scale_i,':'    .reverse_splits_i, .cache_len_i, .splits_i, .page_size_i, .value_scale_i,',
        }
    elif name==FILES[2]:
        changes={'    .cache_len_i(length_q),':'    .reverse_splits_i(descriptor_i[24]), .cache_len_i(length_q),'}
    else:raise ValueError('unexpected P2 projected module')
    for old,new in changes.items():source=replace_once(source,old,new)
    return source


def expected_tokens(item):
    shape=item['case']['shape'];length=shape['length'];splits=shape['splits']
    if length<1 or splits not in (1,2,4) or splits>length:raise ValueError('legal mini split configuration required')
    chunk=(length+splits-1)//splits
    pieces=[list(range(start,min(start+chunk,length))) for start in range(0,length,chunk)]
    return [token for piece in reversed(pieces) for token in piece]


def check_arrival(item,trace):
    if item['case']['scenario']!='arrival-order':raise ValueError('explicit reverse-order case required')
    layout=item['inputs']['layout'];page=layout['page_size'];length=item['case']['shape']['length']
    locations={0x4000+(layout['pages'][token//page]*page+token%page)*32:token for token in range(length)}
    if len(locations)!=length:raise ValueError('ambiguous physical page alias')
    actual=[locations[address] for address,write in trace if write==0 and address in locations]
    expected=expected_tokens(item)*(item['case']['shape']['query']*8)
    if actual!=expected:raise ValueError('real DMA reads did not execute every lane in requested reverse split order')
    return dict(status='PASS',source='actual-accepted-DMA-addresses',descriptor_operator_arg=1,
        expected_token_order=expected,actual_token_order=actual,canonical_merge_order='ascending-split-id',
        scope='serial-split-execution-order-not-concurrent-arrival-interface')


def harness(source):
    source=replace_once(source,'from soc_ai_labs.rtl_oracle import fp32_bits',
        'from soc_ai_labs.rtl_oracle import fp32_bits\nfrom scripts.student_mini_p2_order import check_arrival,FILES')
    source=replace_once(source,'words=[1|(2<<8),',"words=[1|(2<<8)|(int(item['case']['scenario']=='arrival-order')<<24),")
    source=replace_once(source,"            if case['scenario']=='arrival-order':missing.append('out-of-order-split-protocol-witness')",
        "            order_witness=check_arrival(item,trace) if case['scenario']=='arrival-order' else None")
    source=replace_once(source,'reset_observation=reset_observation,source=',
        'split_order_witness=order_witness,reset_observation=reset_observation,source=')
    source=replace_once(source,"    launch('student_mini_p2','p2_student_mini_top',sources,",
        "    project=Path(os.environ['STUDENT_MINI_P2_ORDER_PROJECT'])\n"
        "    sources=[str(project/Path(p).name) if Path(p).name in FILES else p for p in sources]\n"
        "    launch(os.environ['STUDENT_MINI_ORDER_BUILD'],'p2_student_mini_top',sources,")
    return replace_once(source,"test_module='student_mini_p2'","test_module='student_mini_p2_order'")
