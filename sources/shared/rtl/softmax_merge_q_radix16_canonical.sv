// SPDX-License-Identifier: Apache-2.0
// Candidate-local canonical radix-16 merge.
//
// The four base-16 digits are explicit small products, but all four terms are
// reduced in the registered response boundary after the synchronous exp LUT.
// This preserves the exact magnitude/RNE contract without the eight extra
// MULTIPLY/ACCUMULATE bubbles of the historical timing experiment.
module softmax_merge_q_radix16 (
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
  typedef enum logic [1:0] {IDLE, WAIT_EXP, RESPONSE} state_t;
  state_t state_q;

  logic signed [15:0] merged_max_w;
  logic signed [16:0] left_delta_wide, right_delta_wide;
  logic signed [15:0] left_delta_w, right_delta_w;
  logic left_exp_valid, right_exp_valid;
  logic [15:0] left_scale_w, right_scale_w;
  logic [47:0] left_sum_q, right_sum_q;
  logic [63:0] left_weighted_mag_q, right_weighted_mag_q;
  logic left_weighted_negative_q, right_weighted_negative_q;

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
    .x_q11_i(left_delta_w), .valid_o(left_exp_valid), .exp_q15_o(left_scale_w)
  );
  exp_neg_q15_sync u_right_exp (
    .clk_i, .rst_ni, .valid_i(req_valid_i && req_ready_o),
    .x_q11_i(right_delta_w), .valid_o(right_exp_valid), .exp_q15_o(right_scale_w)
  );

  logic [63:0] left_sum_product_w, right_sum_product_w;
  logic [79:0] left_weighted_product_w, right_weighted_product_w;
  always_comb begin
    left_sum_product_w =
      (64'(left_sum_q) * 64'(left_scale_w[3:0])) +
      ((64'(left_sum_q) * 64'(left_scale_w[7:4])) << 4) +
      ((64'(left_sum_q) * 64'(left_scale_w[11:8])) << 8) +
      ((64'(left_sum_q) * 64'(left_scale_w[15:12])) << 12);
    right_sum_product_w =
      (64'(right_sum_q) * 64'(right_scale_w[3:0])) +
      ((64'(right_sum_q) * 64'(right_scale_w[7:4])) << 4) +
      ((64'(right_sum_q) * 64'(right_scale_w[11:8])) << 8) +
      ((64'(right_sum_q) * 64'(right_scale_w[15:12])) << 12);
    left_weighted_product_w =
      (80'(left_weighted_mag_q) * 80'(left_scale_w[3:0])) +
      ((80'(left_weighted_mag_q) * 80'(left_scale_w[7:4])) << 4) +
      ((80'(left_weighted_mag_q) * 80'(left_scale_w[11:8])) << 8) +
      ((80'(left_weighted_mag_q) * 80'(left_scale_w[15:12])) << 12);
    right_weighted_product_w =
      (80'(right_weighted_mag_q) * 80'(right_scale_w[3:0])) +
      ((80'(right_weighted_mag_q) * 80'(right_scale_w[7:4])) << 4) +
      ((80'(right_weighted_mag_q) * 80'(right_scale_w[11:8])) << 8) +
      ((80'(right_weighted_mag_q) * 80'(right_scale_w[15:12])) << 12);
  end

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

  function automatic signed [63:0] rne_shift15_magnitude(
    input logic [79:0] magnitude,
    input logic negative
  );
    logic [79:0] quotient, rounded;
    logic [14:0] remainder;
    begin
      quotient = magnitude >> 15;
      remainder = magnitude[14:0];
      rounded = quotient +
        80'((remainder > 15'd16384) ||
            ((remainder == 15'd16384) && quotient[0]));
      rne_shift15_magnitude = negative ?
        -$signed(rounded[63:0]) : $signed(rounded[63:0]);
    end
  endfunction

  logic [63:0] left_sum_rescaled_w, right_sum_rescaled_w;
  logic signed [63:0] left_weighted_rescaled_w, right_weighted_rescaled_w;
  assign left_sum_rescaled_w = rne_shift15_unsigned(left_sum_product_w);
  assign right_sum_rescaled_w = rne_shift15_unsigned(right_sum_product_w);
  assign left_weighted_rescaled_w = rne_shift15_magnitude(
    left_weighted_product_w, left_weighted_negative_q);
  assign right_weighted_rescaled_w = rne_shift15_magnitude(
    right_weighted_product_w, right_weighted_negative_q);

  assign req_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      merged_max_o <= '0;
      merged_sum_o <= '0;
      merged_weighted_o <= '0;
      left_sum_q <= '0;
      right_sum_q <= '0;
      left_weighted_mag_q <= '0;
      right_weighted_mag_q <= '0;
      left_weighted_negative_q <= 1'b0;
      right_weighted_negative_q <= 1'b0;
    end else begin
      unique case (state_q)
        IDLE: if (req_valid_i) begin
          merged_max_o <= merged_max_w;
          left_sum_q <= left_sum_i;
          right_sum_q <= right_sum_i;
          left_weighted_mag_q <= left_weighted_i[63] ?
            (~left_weighted_i + 1'b1) : left_weighted_i;
          right_weighted_mag_q <= right_weighted_i[63] ?
            (~right_weighted_i + 1'b1) : right_weighted_i;
          left_weighted_negative_q <= left_weighted_i[63];
          right_weighted_negative_q <= right_weighted_i[63];
          state_q <= WAIT_EXP;
        end
        WAIT_EXP: if (left_exp_valid && right_exp_valid) begin
          merged_sum_o <= left_sum_rescaled_w[47:0] + right_sum_rescaled_w[47:0];
          merged_weighted_o <= left_weighted_rescaled_w + right_weighted_rescaled_w;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
