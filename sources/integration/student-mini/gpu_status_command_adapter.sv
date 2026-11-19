// Host command adapter with a read-only device status register at DCR
// address STATUS_ADDR: {30'b0, busy, sticky bus fault}, sampled when the read
// is accepted and returned two cycles later.  Status reads are answered locally and never forwarded to the core; all other commands are
// unchanged from the boundary vortex_command_adapter.
module gpu_status_command_adapter #(
    parameter int ADDR_WIDTH = 12,
    parameter int DATA_WIDTH = 32
) (
    input  logic                  clk_i,
    input  logic                  rst_ni,
    input  logic                  host_cmd_valid_i,
    output logic                  host_cmd_ready_o,
    input  logic [1:0]            host_cmd_kind_i,
    input  logic [ADDR_WIDTH-1:0] host_cmd_addr_i,
    input  logic [DATA_WIDTH-1:0] host_cmd_data_i,
    output logic                  host_rsp_valid_o,
    input  logic                  host_rsp_ready_i,
    output logic [DATA_WIDTH-1:0] host_rsp_data_o,
    output logic                  host_rsp_error_o,
    output logic                  dcr_req_valid_o,
    output logic                  dcr_req_rw_o,
    output logic [ADDR_WIDTH-1:0] dcr_req_addr_o,
    output logic [DATA_WIDTH-1:0] dcr_req_data_o,
    input  logic                  dcr_rsp_valid_i,
    input  logic [DATA_WIDTH-1:0] dcr_rsp_data_i,
    output logic                  start_o,
    input  logic                  busy_i,
    input  logic                  bus_fault_i
);
  localparam logic [1:0] CMD_DCR_WRITE = 2'd0;
  localparam logic [1:0] CMD_DCR_READ  = 2'd1;
  localparam logic [1:0] CMD_START     = 2'd2;
  localparam logic [ADDR_WIDTH-1:0] STATUS_ADDR = '1;
  typedef enum logic [1:0] {IDLE, WAIT_DCR, RESP, WAIT_STATUS} state_t;
  state_t state_q;
  logic [DATA_WIDTH-1:0] response_q;
  logic response_error_q;

  always_comb begin
    host_cmd_ready_o = state_q == IDLE
        && (host_cmd_kind_i != CMD_START || !busy_i);
    host_rsp_valid_o = state_q == RESP;
    host_rsp_data_o = response_q;
    host_rsp_error_o = response_error_q;
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      response_q <= '0;
      response_error_q <= 1'b0;
      dcr_req_valid_o <= 1'b0;
      dcr_req_rw_o <= 1'b0;
      dcr_req_addr_o <= '0;
      dcr_req_data_o <= '0;
      start_o <= 1'b0;
    end else begin
      dcr_req_valid_o <= 1'b0;
      start_o <= 1'b0;
      case (state_q)
        IDLE: begin
          response_error_q <= 1'b0;
          if (host_cmd_valid_i && host_cmd_ready_o) begin
            case (host_cmd_kind_i)
              CMD_DCR_WRITE: begin
                dcr_req_valid_o <= 1'b1;
                dcr_req_rw_o <= 1'b1;
                dcr_req_addr_o <= host_cmd_addr_i;
                dcr_req_data_o <= host_cmd_data_i;
                response_q <= '0;
                state_q <= RESP;
              end
              CMD_DCR_READ: if (host_cmd_addr_i == STATUS_ADDR) begin
                response_q <= {{(DATA_WIDTH-2){1'b0}}, busy_i, bus_fault_i};
                state_q <= WAIT_STATUS;
              end else begin
                dcr_req_valid_o <= 1'b1;
                dcr_req_rw_o <= 1'b0;
                dcr_req_addr_o <= host_cmd_addr_i;
                dcr_req_data_o <= host_cmd_data_i;
                state_q <= WAIT_DCR;
              end
              CMD_START: begin
                start_o <= 1'b1;
                response_q <= '0;
                state_q <= RESP;
              end
              default: begin
                response_q <= '0;
                response_error_q <= 1'b1;
                state_q <= RESP;
              end
            endcase
          end
        end
        WAIT_DCR: begin
          if (dcr_rsp_valid_i) begin
            response_q <= dcr_rsp_data_i;
            state_q <= RESP;
          end
        end
        WAIT_STATUS: state_q <= RESP;
        RESP: if (host_rsp_ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
