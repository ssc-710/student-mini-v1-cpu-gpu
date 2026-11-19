module cpu_wishbone_litedram_adapter (
    input  logic        clk_i,
    input  logic        rst_ni,

    input  logic        i_wb_cyc_i,
    input  logic        i_wb_stb_i,
    input  logic        i_wb_we_i,
    input  logic [29:0] i_wb_adr_i,
    input  logic [31:0] i_wb_dat_i,
    input  logic [3:0]  i_wb_sel_i,
    output logic        i_wb_ack_o,
    output logic        i_wb_err_o,
    output logic [31:0] i_wb_dat_o,

    input  logic        d_wb_cyc_i,
    input  logic        d_wb_stb_i,
    input  logic        d_wb_we_i,
    input  logic [29:0] d_wb_adr_i,
    input  logic [31:0] d_wb_dat_i,
    input  logic [3:0]  d_wb_sel_i,
    output logic        d_wb_ack_o,
    output logic        d_wb_err_o,
    output logic [31:0] d_wb_dat_o,

    output logic        native_cmd_valid_o,
    input  logic        native_cmd_ready_i,
    output logic        native_cmd_we_o,
    output logic [29:0] native_cmd_addr_o,
    output logic        native_wdata_valid_o,
    input  logic        native_wdata_ready_i,
    output logic [31:0] native_wdata_o,
    output logic [3:0]  native_wdata_we_o,
    input  logic        native_rdata_valid_i,
    output logic        native_rdata_ready_o,
    input  logic [31:0] native_rdata_i,
    input  logic        native_error_i
);
  typedef enum logic [2:0] {IDLE, ISSUE, READ_RSP, WB_RSP} state_t;
  state_t state_q;
  logic owner_d_q, last_owner_d_q;
  logic request_we_q;
  logic [29:0] request_addr_q;
  logic [31:0] request_data_q, response_data_q;
  logic [3:0] request_sel_q;
  logic response_error_q;
  logic cmd_sent_q, wdata_sent_q;

  wire i_request = i_wb_cyc_i && i_wb_stb_i;
  wire d_request = d_wb_cyc_i && d_wb_stb_i;
  wire choose_d = d_request && (!i_request || !last_owner_d_q);
  wire cmd_fire = native_cmd_valid_o && native_cmd_ready_i;
  wire wdata_fire = native_wdata_valid_o && native_wdata_ready_i;
  wire cmd_complete = cmd_sent_q || cmd_fire;
  wire wdata_complete = !request_we_q || wdata_sent_q || wdata_fire;

  always_comb begin
    i_wb_ack_o = 1'b0;
    i_wb_err_o = 1'b0;
    i_wb_dat_o = response_data_q;
    d_wb_ack_o = 1'b0;
    d_wb_err_o = 1'b0;
    d_wb_dat_o = response_data_q;
    native_cmd_valid_o = (state_q == ISSUE) && !cmd_sent_q;
    native_cmd_we_o = request_we_q;
    native_cmd_addr_o = request_addr_q;
    native_wdata_valid_o = (state_q == ISSUE) && request_we_q && !wdata_sent_q;
    native_wdata_o = request_data_q;
    native_wdata_we_o = request_sel_q;
    native_rdata_ready_o = (state_q == READ_RSP);
    if (state_q == WB_RSP) begin
      if (owner_d_q) begin
        d_wb_ack_o = 1'b1;
        d_wb_err_o = response_error_q;
      end else begin
        i_wb_ack_o = 1'b1;
        i_wb_err_o = response_error_q;
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      owner_d_q <= 1'b0;
      last_owner_d_q <= 1'b0;
      request_we_q <= 1'b0;
      request_addr_q <= '0;
      request_data_q <= '0;
      request_sel_q <= '0;
      response_data_q <= '0;
      response_error_q <= 1'b0;
      cmd_sent_q <= 1'b0;
      wdata_sent_q <= 1'b0;
    end else begin
      case (state_q)
        IDLE: begin
          cmd_sent_q <= 1'b0;
          wdata_sent_q <= 1'b0;
          response_error_q <= 1'b0;
          if (i_request || d_request) begin
            owner_d_q <= choose_d;
            last_owner_d_q <= choose_d;
            request_we_q <= choose_d ? d_wb_we_i : i_wb_we_i;
            request_addr_q <= choose_d ? d_wb_adr_i : i_wb_adr_i;
            request_data_q <= choose_d ? d_wb_dat_i : i_wb_dat_i;
            request_sel_q <= choose_d ? d_wb_sel_i : i_wb_sel_i;
            state_q <= ISSUE;
          end
        end
        ISSUE: begin
          if (cmd_fire) cmd_sent_q <= 1'b1;
          if (wdata_fire) wdata_sent_q <= 1'b1;
          if (cmd_complete && wdata_complete) begin
            if (request_we_q) begin
              response_data_q <= '0;
              response_error_q <= native_error_i;
              state_q <= WB_RSP;
            end else begin
              state_q <= READ_RSP;
            end
          end
        end
        READ_RSP: begin
          if (native_rdata_valid_i) begin
            response_data_q <= native_rdata_i;
            response_error_q <= native_error_i;
            state_q <= WB_RSP;
          end
        end
        WB_RSP: state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
