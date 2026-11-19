// Blocking correctness prototype for a VexRiscv P3 custom instruction.
//
// The adapter does not contain a multiplier. It arbitrates one request onto
// the existing MulPlugin datapath, waits for the returned product, and feeds
// the post-multiply elastic finish pipeline. The intended custom encoding is
// custom-0/funct3=000/funct7=0101010. rs2 carries the prepared scale context:
//   rs2[23:0]  significand
//   rs2[29:24] signed shift in [-28, 4]
//   rs2[31:30] reserved, must be zero
// The MulPlugin arbiter must pipe owner/tag alongside the product and clear
// every response-valid bit on whole-core reset. The eight-bit tag cannot wrap
// within the fixed MulPlugin response lifetime (checked at whole-core binding).
module cpu_p3_vex_blocking_adapter (
    input  logic               clk,
    input  logic               reset,
    input  logic               flush,

    input  logic               decode_valid,
    input  logic        [31:0] decode_instruction,
    input  logic signed [31:0] decode_rs1,
    input  logic        [31:0] decode_rs2,
    input  logic         [4:0] decode_rd,
    output logic               decode_claim,
    output logic               decode_legal,
    output logic               decode_ready,
    output logic               core_halt,

    // Existing MulPlugin arbitration boundary. Both operands are unsigned:
    // abs(rs1) * zero_extend(significand). An external arbiter preserves
    // ordinary MUL priority/coexistence and returns the corresponding result.
    // owner/tag prevents ordinary or killed pre-flush responses from being
    // mistaken for the current custom transaction.
    input  logic               ordinary_mul_busy,
    output logic               mul_req_valid,
    input  logic               mul_req_ready,
    output logic        [31:0] mul_req_a,
    output logic        [31:0] mul_req_b,
    output logic         [7:0] mul_req_tag,
    input  logic               mul_rsp_valid,
    input  logic        [63:0] mul_rsp_product,
    input  logic               mul_rsp_owner_p3,
    input  logic         [7:0] mul_rsp_tag,

    output logic               wb_valid,
    input  logic               wb_ready,
    output logic         [4:0] wb_rd,
    output logic signed [31:0] wb_data,
    output logic               protocol_error
);
    localparam logic [6:0] P3_OPCODE = 7'b0001011;
    localparam logic [2:0] P3_FUNCT3 = 3'b000;
    localparam logic [6:0] P3_FUNCT7 = 7'b0101010;

    typedef enum logic [1:0] {
        IDLE,
        MUL_REQUEST,
        MUL_RESPONSE,
        FINISH_RESPONSE
    } state_t;

    state_t state_q;
    logic        negative_q;
    logic [31:0] magnitude_q;
    logic [23:0] significand_q;
    logic signed [5:0] shift_q;
    logic  [4:0] rd_q;
    logic  [7:0] active_tag_q;
    logic  [7:0] next_tag_q;

    logic finish_input_ready;
    logic finish_input_valid;
    logic finish_output_valid;
    logic signed [15:0] finish_output_result;
    logic [4:0] finish_output_rd;

    assign decode_claim = decode_instruction[6:0] == P3_OPCODE
        && decode_instruction[14:12] == P3_FUNCT3
        && decode_instruction[31:25] == P3_FUNCT7;
    assign decode_legal = decode_claim
        && decode_rs2[31:30] == 2'b00
        && $signed(decode_rs2[29:24]) >= -28
        && $signed(decode_rs2[29:24]) <= 4;
    assign decode_ready = state_q == IDLE && !ordinary_mul_busy
        && !flush && !reset;
    assign core_halt = state_q != IDLE;

    assign mul_req_valid = state_q == MUL_REQUEST && !flush && !reset;
    assign mul_req_a = magnitude_q;
    assign mul_req_b = {8'd0, significand_q};
    assign mul_req_tag = active_tag_q;

    assign finish_input_valid = state_q == MUL_RESPONSE && mul_rsp_valid
        && mul_rsp_owner_p3 && mul_rsp_tag == active_tag_q;
    assign wb_valid = state_q == FINISH_RESPONSE && finish_output_valid
        && !flush && !reset;
    assign wb_rd = finish_output_rd;
    assign wb_data = {{16{finish_output_result[15]}}, finish_output_result};

    cpu_p3_scale_finish_elastic finish (
        .clk(clk),
        .reset(reset),
        .flush(flush),
        .input_ready(finish_input_ready),
        .input_valid(finish_input_valid),
        .input_negative(negative_q),
        .input_product(mul_rsp_product[55:0]),
        .input_shift(shift_q),
        .input_rd(rd_q),
        .output_ready(wb_ready),
        .output_valid(finish_output_valid),
        .output_result(finish_output_result),
        .output_rd(finish_output_rd)
    );

    always_ff @(posedge clk) begin
        if (reset) begin
            state_q <= IDLE;
            negative_q <= 1'b0;
            magnitude_q <= 32'd0;
            significand_q <= 24'd0;
            shift_q <= 6'sd0;
            rd_q <= 5'd0;
            active_tag_q <= 8'd0;
            next_tag_q <= 8'd0;
            protocol_error <= 1'b0;
        end else if (flush) begin
            state_q <= IDLE;
            negative_q <= 1'b0;
            magnitude_q <= 32'd0;
            significand_q <= 24'd0;
            shift_q <= 6'sd0;
            rd_q <= 5'd0;
            protocol_error <= 1'b0;
        end else begin
            case (state_q)
                IDLE: begin
                    if (decode_valid && decode_legal && decode_ready) begin
                        negative_q <= decode_rs1[31];
                        magnitude_q <= decode_rs1[31]
                            ? (~decode_rs1 + 32'd1) : decode_rs1;
                        significand_q <= decode_rs2[23:0];
                        shift_q <= decode_rs2[29:24];
                        rd_q <= decode_rd;
                        active_tag_q <= next_tag_q;
                        next_tag_q <= next_tag_q + 8'd1;
                        state_q <= MUL_REQUEST;
                    end
                end
                MUL_REQUEST: begin
                    if (mul_req_valid && mul_req_ready)
                        state_q <= MUL_RESPONSE;
                end
                MUL_RESPONSE: begin
                    if (mul_rsp_valid && mul_rsp_owner_p3
                            && mul_rsp_tag == active_tag_q
                            && finish_input_ready) begin
                        if (mul_rsp_product[63:56] != 8'd0)
                            protocol_error <= 1'b1;
                        state_q <= FINISH_RESPONSE;
                    end
                end
                FINISH_RESPONSE: begin
                    if (wb_valid && wb_ready)
                        state_q <= IDLE;
                end
                default: state_q <= IDLE;
            endcase
        end
    end
endmodule
