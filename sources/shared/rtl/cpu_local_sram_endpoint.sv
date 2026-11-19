module cpu_local_sram_endpoint (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic        cmd_valid_i,
    output logic        cmd_ready_o,
    input  logic        cmd_we_i,
    input  logic [29:0] cmd_addr_i,
    input  logic        wdata_valid_i,
    output logic        wdata_ready_o,
    input  logic [31:0] wdata_i,
    input  logic [3:0]  wdata_we_i,
    output logic        rdata_valid_o,
    input  logic        rdata_ready_i,
    output logic [31:0] rdata_o,
    output logic        error_o
);
  typedef enum logic [1:0] {IDLE, READ_WAIT, READ_RSP} state_t;
  state_t state_q;
  logic [1:0] read_word_q;
  logic [31:0] read_data_q;
  logic [128:0] macro_din, macro_dout;
  logic [15:0] macro_wmask;
  logic [8:0] macro_addr;
  logic macro_csb, macro_web;

  wire write_fire = cmd_valid_i && cmd_ready_o && cmd_we_i;
  wire read_fire = cmd_valid_i && cmd_ready_o && !cmd_we_i;

  always_comb begin
    cmd_ready_o = (state_q == IDLE) && (!cmd_we_i || wdata_valid_i);
    wdata_ready_o = (state_q == IDLE) && cmd_valid_i && cmd_we_i;
    rdata_valid_o = (state_q == READ_RSP);
    rdata_o = read_data_q;
    error_o = 1'b0;

    macro_csb = !(write_fire || read_fire);
    macro_web = !write_fire;
    macro_addr = cmd_addr_i[10:2];
    macro_din = '0;
    macro_wmask = '0;
    case (cmd_addr_i[1:0])
      2'd0: begin macro_din[31:0] = wdata_i; macro_wmask[3:0] = wdata_we_i; end
      2'd1: begin macro_din[63:32] = wdata_i; macro_wmask[7:4] = wdata_we_i; end
      2'd2: begin macro_din[95:64] = wdata_i; macro_wmask[11:8] = wdata_we_i; end
      default: begin macro_din[127:96] = wdata_i; macro_wmask[15:12] = wdata_we_i; end
    endcase
  end

  openram_128x256 local_sram (
    .clk0(clk_i), .csb0(macro_csb), .web0(macro_web),
    .wmask0(macro_wmask), .spare_wen0(1'b0), .addr0(macro_addr),
    .din0(macro_din), .dout0(macro_dout)
  );

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      read_word_q <= '0;
      read_data_q <= '0;
    end else begin
      case (state_q)
        IDLE: if (read_fire) begin
          read_word_q <= cmd_addr_i[1:0];
          state_q <= READ_WAIT;
        end
        READ_WAIT: begin
          case (read_word_q)
            2'd0: read_data_q <= macro_dout[31:0];
            2'd1: read_data_q <= macro_dout[63:32];
            2'd2: read_data_q <= macro_dout[95:64];
            default: read_data_q <= macro_dout[127:96];
          endcase
          state_q <= READ_RSP;
        end
        READ_RSP: if (rdata_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
