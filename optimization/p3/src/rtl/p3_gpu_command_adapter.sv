// Tag-preserving ready/valid seam around Vortex's pulse-only native DCR.
module p3_gpu_command_adapter #(parameter int ADDR_WIDTH=12, DATA_WIDTH=32) (
 input logic clk_i, rst_ni, host_cmd_valid_i, output logic host_cmd_ready_o,
 input logic [1:0] host_cmd_kind_i, input logic [ADDR_WIDTH-1:0] host_cmd_addr_i,
 input logic [DATA_WIDTH-1:0] host_cmd_data_i, output logic host_rsp_valid_o,
 input logic host_rsp_ready_i, output logic [DATA_WIDTH-1:0] host_rsp_data_o,
 output logic host_rsp_error_o, output logic dcr_req_valid_o,
 output logic dcr_req_rw_o, output logic [ADDR_WIDTH-1:0] dcr_req_addr_o,
 output logic [DATA_WIDTH-1:0] dcr_req_data_o, input logic dcr_rsp_valid_i,
 input logic [DATA_WIDTH-1:0] dcr_rsp_data_i, output logic start_o, input logic busy_i);
 localparam logic [1:0] WRITE=2'd0, READ=2'd1, START=2'd2;
 typedef enum logic [1:0] {IDLE, WAIT_DCR, RESP} state_t;
 state_t state_q; logic [DATA_WIDTH-1:0] data_q; logic error_q;
 always_comb begin
   host_cmd_ready_o = state_q==IDLE && (host_cmd_kind_i!=START || !busy_i);
   host_rsp_valid_o = state_q==RESP; host_rsp_data_o=data_q; host_rsp_error_o=error_q;
 end
 always_ff @(posedge clk_i) begin
   if (!rst_ni) begin state_q<=IDLE; data_q<='0; error_q<=0; dcr_req_valid_o<=0;
     dcr_req_rw_o<=0; dcr_req_addr_o<='0; dcr_req_data_o<='0; start_o<=0; end
   else begin
     dcr_req_valid_o<=0; start_o<=0;
     case (state_q)
       IDLE: if (host_cmd_valid_i && host_cmd_ready_o) begin
         error_q<=0; dcr_req_addr_o<=host_cmd_addr_i; dcr_req_data_o<=host_cmd_data_i;
         case(host_cmd_kind_i)
           WRITE: begin dcr_req_valid_o<=1; dcr_req_rw_o<=1; data_q<='0; state_q<=RESP; end
           READ: begin dcr_req_valid_o<=1; dcr_req_rw_o<=0; state_q<=WAIT_DCR; end
           START: begin start_o<=1; data_q<='0; state_q<=RESP; end
           default: begin error_q<=1; data_q<='0; state_q<=RESP; end
         endcase end
       WAIT_DCR: if (dcr_rsp_valid_i) begin data_q<=dcr_rsp_data_i; state_q<=RESP; end
       RESP: if (host_rsp_ready_i) state_q<=IDLE;
       default: state_q<=IDLE;
     endcase
   end
 end
endmodule
