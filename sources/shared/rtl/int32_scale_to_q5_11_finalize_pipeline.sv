// SPDX-License-Identifier: Apache-2.0
// Bit-exact INT32*FP32 -> Q5.11 converter with bounded shift stages.  The
// frozen scale range makes at most three byte shifts necessary; sticky bits
// preserve the original one-shot RNE result.
module int32_scale_to_q5_11_finalize_pipeline #(
  parameter bit REQUIRE_PROJECT_SCALE_RANGE = 1'b1
) (
  input logic clk_i, input logic rst_ni,
  input logic cmd_valid_i, output logic cmd_ready_o,
  input logic signed [31:0] value_i, input logic [31:0] scale_i,
  output logic rsp_valid_o, input logic rsp_ready_i,
  output logic signed [15:0] q5_11_o, output logic scale_valid_o
);
  typedef enum logic [3:0] {
    IDLE, MULTIPLY_PARTS, COMBINE, PREP_SHIFT, SHIFT_COARSE,
    SHIFT_FINE, SHIFT_LEFT, FORMAT, RESPONSE
  } state_t;
  state_t state_q;

  logic sign_q, valid_q, sticky_q;
  logic [7:0] exponent_q;
  logic [23:0] significand_q;
  logic [31:0] magnitude_q;
  logic [39:0] low_product_q, high_product_q;
  logic [55:0] product_q;
  logic [95:0] work_q;
  logic [5:0] shift_count_q;
  logic signed [15:0] result_q;
  logic contract_scale_valid_w, relaxed_scale_valid_w, scale_valid_w;

  logic [95:0] fine_quotient_w, fine_mask_w, fine_remainder_w;
  logic [95:0] fine_half_w, fine_rounded_w;
  logic fine_increment_w;

  fp32_scale_check u_scale_check (
    .scale_i(scale_i), .valid_o(contract_scale_valid_w));
  assign relaxed_scale_valid_w = !scale_i[31] && scale_i[30:23] != 0 &&
                                 scale_i[30:23] != 8'hff;
  assign scale_valid_w = REQUIRE_PROJECT_SCALE_RANGE ? contract_scale_valid_w :
                         relaxed_scale_valid_w;

  always_comb begin
    fine_quotient_w = work_q;
    fine_mask_w = '0;
    fine_remainder_w = '0;
    fine_half_w = '0;
    fine_increment_w = 1'b0;
    fine_rounded_w = work_q;
    if (shift_count_q != 0) begin
      fine_quotient_w = work_q >> shift_count_q[2:0];
      fine_mask_w = (96'd1 << shift_count_q[2:0]) - 1'b1;
      fine_remainder_w = work_q & fine_mask_w;
      fine_half_w = 96'd1 << (shift_count_q[2:0] - 1'b1);
      fine_increment_w = (fine_remainder_w > fine_half_w) ||
        ((fine_remainder_w == fine_half_w) &&
         (sticky_q || fine_quotient_w[0]));
      fine_rounded_w = fine_quotient_w + {{95{1'b0}}, fine_increment_w};
    end
  end

  assign cmd_ready_o = state_q == IDLE;
  assign rsp_valid_o = state_q == RESPONSE;
  assign q5_11_o = result_q;
  assign scale_valid_o = valid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      sign_q <= '0; valid_q <= '0; sticky_q <= '0; exponent_q <= '0;
      significand_q <= '0; magnitude_q <= '0;
      low_product_q <= '0; high_product_q <= '0; product_q <= '0;
      work_q <= '0; shift_count_q <= '0; result_q <= '0;
    end else begin
      unique case (state_q)
        IDLE: if (cmd_valid_i) begin
          sign_q <= value_i[31];
          valid_q <= scale_valid_w;
          sticky_q <= 1'b0;
          exponent_q <= scale_i[30:23];
          significand_q <= {1'b1, scale_i[22:0]};
          magnitude_q <= value_i[31] ? (~value_i + 1'b1) : value_i;
          result_q <= '0;
          if (!scale_valid_w || value_i == 0) state_q <= RESPONSE;
          else state_q <= MULTIPLY_PARTS;
        end
        MULTIPLY_PARTS: begin
          low_product_q <= magnitude_q[15:0] * significand_q;
          high_product_q <= magnitude_q[31:16] * significand_q;
          state_q <= COMBINE;
        end
        COMBINE: begin
          product_q <= {high_product_q, 16'd0} +
                       {{16{1'b0}}, low_product_q};
          state_q <= PREP_SHIFT;
        end
        PREP_SHIFT: begin
          work_q <= {40'd0, product_q};
          sticky_q <= 1'b0;
          if (exponent_q >= 8'd139) begin
            shift_count_q <= 6'(exponent_q - 8'd139);
            state_q <= SHIFT_LEFT;
          end else begin
            shift_count_q <= 6'(8'd139 - exponent_q);
            state_q <= SHIFT_COARSE;
          end
        end
        SHIFT_COARSE: begin
          if (shift_count_q > 6'd7) begin
            sticky_q <= sticky_q || |work_q[7:0];
            work_q <= work_q >> 8;
            shift_count_q <= shift_count_q - 6'd8;
          end else state_q <= SHIFT_FINE;
        end
        SHIFT_FINE: begin
          work_q <= fine_rounded_w;
          state_q <= FORMAT;
        end
        SHIFT_LEFT: begin
          work_q <= work_q << shift_count_q[2:0];
          state_q <= FORMAT;
        end
        FORMAT: begin
          if (sign_q) begin
            if (work_q >= 96'd32768) result_q <= -16'sd32768;
            else result_q <= -$signed(work_q[15:0]);
          end else begin
            if (work_q >= 96'd32767) result_q <= 16'sd32767;
            else result_q <= $signed(work_q[15:0]);
          end
          state_q <= RESPONSE;
        end
        RESPONSE: if (rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
