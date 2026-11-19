// SPDX-License-Identifier: Apache-2.0
// Handshaked Split-KV merge with registered exponential lookup outputs.
module softmax_merge_q_sync (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    req_valid_i,
  output logic                    req_ready_o,
  input  logic signed [15:0]      left_max_i,
  input  logic        [47:0]      left_sum_i,
  input  logic signed [63:0]      left_weighted_i,
  input  logic signed [15:0]      right_max_i,
  input  logic        [47:0]      right_sum_i,
  input  logic signed [63:0]      right_weighted_i,
  output logic                    rsp_valid_o,
  input  logic                    rsp_ready_i,
  output logic signed [15:0]      merged_max_o,
  output logic        [47:0]      merged_sum_o,
  output logic signed [63:0]      merged_weighted_o
);
  logic busy_q;
  logic signed [15:0] merged_max_w;
  logic signed [16:0] left_delta_wide, right_delta_wide;
  logic signed [15:0] left_delta_w, right_delta_w;
  logic left_exp_valid, right_exp_valid;
  logic [15:0] left_scale, right_scale;
  logic [47:0] left_sum_q, right_sum_q;
  logic signed [63:0] left_weighted_q, right_weighted_q;

  assign req_ready_o = !busy_q && !rsp_valid_o;
  assign merged_max_w = left_max_i > right_max_i ? left_max_i : right_max_i;
  assign left_delta_wide = {left_max_i[15], left_max_i} -
                           {merged_max_w[15], merged_max_w};
  assign right_delta_wide = {right_max_i[15], right_max_i} -
                            {merged_max_w[15], merged_max_w};
  assign left_delta_w = left_delta_wide < -17'sd32768 ?
                        -16'sd32768 : left_delta_wide[15:0];
  assign right_delta_w = right_delta_wide < -17'sd32768 ?
                         -16'sd32768 : right_delta_wide[15:0];

  exp_neg_q15_sync u_left_exp (
    .clk_i, .rst_ni, .valid_i(req_valid_i && req_ready_o),
    .x_q11_i(left_delta_w), .valid_o(left_exp_valid), .exp_q15_o(left_scale)
  );
  exp_neg_q15_sync u_right_exp (
    .clk_i, .rst_ni, .valid_i(req_valid_i && req_ready_o),
    .x_q11_i(right_delta_w), .valid_o(right_exp_valid), .exp_q15_o(right_scale)
  );

  function automatic [63:0] rne_shift15_unsigned(input logic [63:0] value);
    logic [63:0] quotient;
    logic [14:0] remainder;
    begin
      quotient = value >> 15;
      remainder = value[14:0];
      rne_shift15_unsigned = quotient +
        64'((remainder > 15'd16384) ||
            ((remainder == 15'd16384) && quotient[0]));
    end
  endfunction

  function automatic signed [63:0] rne_shift15_signed(
    input logic signed [80:0] value
  );
    logic negative;
    logic [80:0] magnitude, quotient, rounded;
    logic [14:0] remainder;
    begin
      negative = value[80];
      magnitude = negative ? (~value + 1'b1) : value;
      quotient = magnitude >> 15;
      remainder = magnitude[14:0];
      rounded = quotient +
        81'((remainder > 15'd16384) ||
            ((remainder == 15'd16384) && quotient[0]));
      rne_shift15_signed = negative ?
        -$signed(rounded[63:0]) : $signed(rounded[63:0]);
    end
  endfunction

  logic [63:0] left_sum_product_w, right_sum_product_w;
  logic signed [80:0] left_weighted_product_w, right_weighted_product_w;
  logic [63:0] left_sum_rescaled_w, right_sum_rescaled_w;
  logic signed [63:0] left_weighted_rescaled_w, right_weighted_rescaled_w;
  assign left_sum_product_w = left_sum_q * left_scale;
  assign right_sum_product_w = right_sum_q * right_scale;
  assign left_weighted_product_w = left_weighted_q * $signed({1'b0, left_scale});
  assign right_weighted_product_w = right_weighted_q * $signed({1'b0, right_scale});
  assign left_sum_rescaled_w = rne_shift15_unsigned(left_sum_product_w);
  assign right_sum_rescaled_w = rne_shift15_unsigned(right_sum_product_w);
  assign left_weighted_rescaled_w = rne_shift15_signed(left_weighted_product_w);
  assign right_weighted_rescaled_w = rne_shift15_signed(right_weighted_product_w);

`ifdef P2_MERGE_PRODUCT_PIPELINE
  // The radix-16 implementation already honours this timing-foundation
  // define.  Keep the canonical scalar merge arithmetic unchanged, but give
  // its wide products the same explicit register boundary.  This is a B0
  // feasibility cut: it neither changes the merge radix nor consumes the
  // radix-16 promotion mechanism.
  logic product_valid_q;
  logic [63:0] left_sum_product_q, right_sum_product_q;
  logic signed [80:0] left_weighted_product_q, right_weighted_product_q;
  logic [63:0] left_sum_rescaled_q, right_sum_rescaled_q;
  logic signed [63:0] left_weighted_rescaled_q, right_weighted_rescaled_q;

`ifdef P2_MERGE_RESCALE_PIPELINE
  // The product register removes the wide multipliers from the response
  // stage.  Keep the exact RNE result behind one more feasibility-only B0
  // boundary so the final additions do not share a cycle with RNE.
  logic rescale_valid_q;
  logic [47:0] left_sum_rounded_q, right_sum_rounded_q;
  logic signed [63:0] left_weighted_rounded_q, right_weighted_rounded_q;
`endif

`ifdef P2_MERGE_PRODUCT_STEP_CUT
  // B0-only two-step product boundary.  This is a pair of fixed byte
  // partials, not the four-digit iterative radix-16 merge reserved for A1.
  // The next stage reconstructs the exact product before the existing RNE.
  logic product_partial_valid_q;
  logic [55:0] left_sum_product_lo_q, left_sum_product_hi_q;
  logic [55:0] right_sum_product_lo_q, right_sum_product_hi_q;
  logic signed [72:0] left_weighted_product_lo_q;
  logic signed [72:0] left_weighted_product_hi_q;
  logic signed [72:0] right_weighted_product_lo_q;
  logic signed [72:0] right_weighted_product_hi_q;
`endif

  assign left_sum_rescaled_q = rne_shift15_unsigned(left_sum_product_q);
  assign right_sum_rescaled_q = rne_shift15_unsigned(right_sum_product_q);
  assign left_weighted_rescaled_q = rne_shift15_signed(left_weighted_product_q);
  assign right_weighted_rescaled_q = rne_shift15_signed(right_weighted_product_q);
`endif

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      busy_q <= 1'b0;
      rsp_valid_o <= 1'b0;
      merged_max_o <= '0;
      merged_sum_o <= '0;
      merged_weighted_o <= '0;
      left_sum_q <= '0;
      right_sum_q <= '0;
      left_weighted_q <= '0;
      right_weighted_q <= '0;
`ifdef P2_MERGE_PRODUCT_PIPELINE
      product_valid_q <= 1'b0;
      left_sum_product_q <= '0;
      right_sum_product_q <= '0;
      left_weighted_product_q <= '0;
      right_weighted_product_q <= '0;
`ifdef P2_MERGE_RESCALE_PIPELINE
      rescale_valid_q <= 1'b0;
      left_sum_rounded_q <= '0;
      right_sum_rounded_q <= '0;
      left_weighted_rounded_q <= '0;
      right_weighted_rounded_q <= '0;
`endif
`ifdef P2_MERGE_PRODUCT_STEP_CUT
      product_partial_valid_q <= 1'b0;
      left_sum_product_lo_q <= '0;
      left_sum_product_hi_q <= '0;
      right_sum_product_lo_q <= '0;
      right_sum_product_hi_q <= '0;
      left_weighted_product_lo_q <= '0;
      left_weighted_product_hi_q <= '0;
      right_weighted_product_lo_q <= '0;
      right_weighted_product_hi_q <= '0;
`endif
`endif
    end else begin
      if (rsp_valid_o && rsp_ready_i) rsp_valid_o <= 1'b0;
      if (req_valid_i && req_ready_o) begin
        busy_q <= 1'b1;
        merged_max_o <= merged_max_w;
        left_sum_q <= left_sum_i;
        right_sum_q <= right_sum_i;
        left_weighted_q <= left_weighted_i;
        right_weighted_q <= right_weighted_i;
      end
      if (busy_q && left_exp_valid && right_exp_valid) begin
`ifdef P2_MERGE_PRODUCT_PIPELINE
`ifdef P2_MERGE_PRODUCT_STEP_CUT
        product_partial_valid_q <= 1'b1;
        left_sum_product_lo_q <= left_sum_q * left_scale[7:0];
        left_sum_product_hi_q <= left_sum_q * left_scale[15:8];
        right_sum_product_lo_q <= right_sum_q * right_scale[7:0];
        right_sum_product_hi_q <= right_sum_q * right_scale[15:8];
        left_weighted_product_lo_q <=
          left_weighted_q * $signed({1'b0, left_scale[7:0]});
        left_weighted_product_hi_q <=
          left_weighted_q * $signed({1'b0, left_scale[15:8]});
        right_weighted_product_lo_q <=
          right_weighted_q * $signed({1'b0, right_scale[7:0]});
        right_weighted_product_hi_q <=
          right_weighted_q * $signed({1'b0, right_scale[15:8]});
`else
        product_valid_q <= 1'b1;
        left_sum_product_q <= left_sum_product_w;
        right_sum_product_q <= right_sum_product_w;
        left_weighted_product_q <= left_weighted_product_w;
        right_weighted_product_q <= right_weighted_product_w;
`endif
`else
        busy_q <= 1'b0;
        rsp_valid_o <= 1'b1;
        merged_sum_o <= left_sum_rescaled_w[47:0] + right_sum_rescaled_w[47:0];
        merged_weighted_o <= left_weighted_rescaled_w +
                             right_weighted_rescaled_w;
`endif
      end
`ifdef P2_MERGE_PRODUCT_PIPELINE
`ifdef P2_MERGE_PRODUCT_STEP_CUT
      if (product_partial_valid_q) begin
        product_partial_valid_q <= 1'b0;
        product_valid_q <= 1'b1;
        left_sum_product_q <= {8'b0, left_sum_product_lo_q} +
                              ({8'b0, left_sum_product_hi_q} << 8);
        right_sum_product_q <= {8'b0, right_sum_product_lo_q} +
                               ({8'b0, right_sum_product_hi_q} << 8);
        left_weighted_product_q <=
          $signed({{8{left_weighted_product_lo_q[72]}},
                   left_weighted_product_lo_q}) +
          ($signed({{8{left_weighted_product_hi_q[72]}},
                    left_weighted_product_hi_q}) <<< 8);
        right_weighted_product_q <=
          $signed({{8{right_weighted_product_lo_q[72]}},
                   right_weighted_product_lo_q}) +
          ($signed({{8{right_weighted_product_hi_q[72]}},
                    right_weighted_product_hi_q}) <<< 8);
      end
`endif
      if (product_valid_q) begin
        product_valid_q <= 1'b0;
`ifdef P2_MERGE_RESCALE_PIPELINE
        rescale_valid_q <= 1'b1;
        left_sum_rounded_q <= left_sum_rescaled_q[47:0];
        right_sum_rounded_q <= right_sum_rescaled_q[47:0];
        left_weighted_rounded_q <= left_weighted_rescaled_q;
        right_weighted_rounded_q <= right_weighted_rescaled_q;
`else
        busy_q <= 1'b0;
        rsp_valid_o <= 1'b1;
        merged_sum_o <= left_sum_rescaled_q[47:0] + right_sum_rescaled_q[47:0];
        merged_weighted_o <= left_weighted_rescaled_q +
                             right_weighted_rescaled_q;
`endif
      end
`ifdef P2_MERGE_RESCALE_PIPELINE
      if (rescale_valid_q) begin
        busy_q <= 1'b0;
        rescale_valid_q <= 1'b0;
        rsp_valid_o <= 1'b1;
        merged_sum_o <= left_sum_rounded_q + right_sum_rounded_q;
        merged_weighted_o <= left_weighted_rounded_q +
                             right_weighted_rounded_q;
      end
`endif
`endif
    end
  end
endmodule
