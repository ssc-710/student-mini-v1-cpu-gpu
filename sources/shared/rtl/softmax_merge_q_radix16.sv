// SPDX-License-Identifier: Apache-2.0
// Bit-exact Split-KV merge with four radix-16 rescale steps.
//
// The frozen merge equation is unchanged.  Replacing each wide 64x16
// combinational multiply with four registered 64x4 digit products removes the
// measured critical path while preserving RNE, signed magnitude handling and
// the ready/valid public seam.
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
  typedef enum logic [2:0] {
    IDLE, WAIT_EXP, MULTIPLY, ACCUMULATE, RESCALE, ADD_RESULTS, RESPONSE
  } state_t;
  state_t state_q;

  logic signed [15:0] merged_max_w;
  logic signed [16:0] left_delta_wide, right_delta_wide;
  logic signed [15:0] left_delta_w, right_delta_w;
  logic left_exp_valid, right_exp_valid;
  logic [15:0] left_exp, right_exp;

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
    .x_q11_i(left_delta_w), .valid_o(left_exp_valid), .exp_q15_o(left_exp)
  );
  exp_neg_q15_sync u_right_exp (
    .clk_i, .rst_ni, .valid_i(req_valid_i && req_ready_o),
    .x_q11_i(right_delta_w), .valid_o(right_exp_valid), .exp_q15_o(right_exp)
  );

  logic [47:0] left_sum_q, right_sum_q;
  logic [63:0] left_weighted_mag_q, right_weighted_mag_q;
  logic left_weighted_negative_q, right_weighted_negative_q;
  logic [15:0] left_scale_q, right_scale_q;
  logic [1:0] digit_q;
  logic [63:0] left_sum_product_q, right_sum_product_q;
  logic [79:0] left_weighted_product_q, right_weighted_product_q;
  logic [63:0] left_sum_digit_product_q, right_sum_digit_product_q;
  logic [67:0] left_weighted_digit_product_q, right_weighted_digit_product_q;
  logic [1:0] product_digit_q;
  logic [63:0] left_sum_rescaled_q, right_sum_rescaled_q;
  logic signed [63:0] left_weighted_rescaled_q, right_weighted_rescaled_q;

  logic [3:0] left_digit_w, right_digit_w;
  logic [5:0] digit_shift_w;
  assign left_digit_w = left_scale_q[digit_q * 4 +: 4];
  assign right_digit_w = right_scale_q[digit_q * 4 +: 4];
  assign digit_shift_w = {2'b00, digit_q, 2'b00};

`ifdef P2_MERGE_PRODUCT_PIPELINE
  localparam bit PIPELINED_DIGIT_PRODUCT = 1'b1;
`else
  localparam bit PIPELINED_DIGIT_PRODUCT = 1'b0;
`endif

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
      left_scale_q <= '0;
      right_scale_q <= '0;
      digit_q <= '0;
      left_sum_product_q <= '0;
      right_sum_product_q <= '0;
      left_weighted_product_q <= '0;
      right_weighted_product_q <= '0;
      left_sum_digit_product_q <= '0;
      right_sum_digit_product_q <= '0;
      left_weighted_digit_product_q <= '0;
      right_weighted_digit_product_q <= '0;
      product_digit_q <= '0;
      left_sum_rescaled_q <= '0;
      right_sum_rescaled_q <= '0;
      left_weighted_rescaled_q <= '0;
      right_weighted_rescaled_q <= '0;
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
          left_scale_q <= left_exp;
          right_scale_q <= right_exp;
          digit_q <= '0;
          left_sum_product_q <= '0;
          right_sum_product_q <= '0;
          left_weighted_product_q <= '0;
          right_weighted_product_q <= '0;
          state_q <= MULTIPLY;
        end
        MULTIPLY: begin
          if (PIPELINED_DIGIT_PRODUCT) begin
            left_sum_digit_product_q <= left_sum_q * left_digit_w;
            right_sum_digit_product_q <= right_sum_q * right_digit_w;
            left_weighted_digit_product_q <= left_weighted_mag_q * left_digit_w;
            right_weighted_digit_product_q <= right_weighted_mag_q * right_digit_w;
            product_digit_q <= digit_q;
            state_q <= ACCUMULATE;
          end else begin
            left_sum_product_q <= left_sum_product_q +
              ((64'(left_sum_q) * 64'(left_digit_w)) << digit_shift_w);
            right_sum_product_q <= right_sum_product_q +
              ((64'(right_sum_q) * 64'(right_digit_w)) << digit_shift_w);
            left_weighted_product_q <= left_weighted_product_q +
              ((80'(left_weighted_mag_q) * 80'(left_digit_w)) << digit_shift_w);
            right_weighted_product_q <= right_weighted_product_q +
              ((80'(right_weighted_mag_q) * 80'(right_digit_w)) << digit_shift_w);
            if (digit_q == 2'd3) state_q <= RESCALE;
            else digit_q <= digit_q + 1'b1;
          end
        end
        ACCUMULATE: begin
          left_sum_product_q <= left_sum_product_q +
            (left_sum_digit_product_q << {product_digit_q, 2'b00});
          right_sum_product_q <= right_sum_product_q +
            (right_sum_digit_product_q << {product_digit_q, 2'b00});
          left_weighted_product_q <= left_weighted_product_q +
            (80'(left_weighted_digit_product_q) << {product_digit_q, 2'b00});
          right_weighted_product_q <= right_weighted_product_q +
            (80'(right_weighted_digit_product_q) << {product_digit_q, 2'b00});
          if (product_digit_q == 2'd3) state_q <= RESCALE;
          else begin digit_q <= product_digit_q + 1'b1; state_q <= MULTIPLY; end
        end
        RESCALE: begin
          left_sum_rescaled_q <= rne_shift15_unsigned(left_sum_product_q);
          right_sum_rescaled_q <= rne_shift15_unsigned(right_sum_product_q);
          left_weighted_rescaled_q <= rne_shift15_magnitude(
            left_weighted_product_q, left_weighted_negative_q);
          right_weighted_rescaled_q <= rne_shift15_magnitude(
            right_weighted_product_q, right_weighted_negative_q);
          state_q <= ADD_RESULTS;
        end
        ADD_RESULTS: begin
          merged_sum_o <= left_sum_rescaled_q[47:0] +
                          right_sum_rescaled_q[47:0];
          merged_weighted_o <= left_weighted_rescaled_q +
                               right_weighted_rescaled_q;
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
