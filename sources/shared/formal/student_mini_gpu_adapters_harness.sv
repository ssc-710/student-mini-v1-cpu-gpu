// Mini GPU physical boundary: two independent 512-bit ports, 26-bit addresses,
// 10-bit tags. Proves adapters only, not GPU core or DRAM implementation.
module student_mini_gpu_adapters_harness;
  (* gclk *) reg clk;
  reg past_valid=0;
  (* anyseq *) reg rst_n;
  (* anyseq *) reg host_valid,host_rsp_ready,busy,dcr_rsp_valid;
  (* anyseq *) reg [1:0] host_kind;
  (* anyseq *) reg [11:0] host_addr;
  (* anyseq *) reg [31:0] host_data,dcr_rsp_data;
  wire host_ready,host_rsp_valid,host_error,dcr_valid,dcr_rw,start;
  wire [11:0] dcr_addr;
  wire [31:0] host_rsp_data,dcr_data;
  reg [1:0] phase=0;
  reg [31:0] expected_response=0;
  reg expected_error=0;
  vortex_command_adapter command_adapter (
    .clk_i(clk),.rst_ni(rst_n),.host_cmd_valid_i(host_valid),.host_cmd_ready_o(host_ready),
    .host_cmd_kind_i(host_kind),.host_cmd_addr_i(host_addr),.host_cmd_data_i(host_data),
    .host_rsp_valid_o(host_rsp_valid),.host_rsp_ready_i(host_rsp_ready),
    .host_rsp_data_o(host_rsp_data),.host_rsp_error_o(host_error),
    .dcr_req_valid_o(dcr_valid),.dcr_req_rw_o(dcr_rw),.dcr_req_addr_o(dcr_addr),
    .dcr_req_data_o(dcr_data),.dcr_rsp_valid_i(dcr_rsp_valid),.dcr_rsp_data_i(dcr_rsp_data),
    .start_o(start),.busy_i(busy));
  always @(posedge clk) begin
    past_valid<=1;
    if (!past_valid) assume(!rst_n);
    if (!rst_n) begin phase<=0;expected_response<=0;expected_error<=0;end
    else case(phase)
      0: if(host_valid && host_ready) begin
        expected_response<=0;expected_error<=host_kind==3;
        phase<=host_kind==1?1:2;
      end
      1: if(dcr_rsp_valid) begin expected_response<=dcr_rsp_data;phase<=2;end
      2: if(host_rsp_ready) phase<=0;
    endcase
    if (past_valid) begin
      assert(host_ready==(phase==0 && (host_kind!=2 || !busy)));
      assert(host_rsp_valid==(phase==2));
      if (host_rsp_valid) begin assert(host_rsp_data==expected_response);assert(host_error==expected_error);end
      if (!$past(rst_n)) begin assert(!host_rsp_valid);assert(!dcr_valid);assert(!start);end
      else begin
        assert(start==$past(host_valid && host_ready && host_kind==2));
        assert(dcr_valid==$past(host_valid && host_ready && host_kind<2));
        if(dcr_valid) begin
          assert(dcr_addr==$past(host_addr));assert(dcr_rw==$past(host_kind==0));
          assert(dcr_data==($past(host_kind)==0?$past(host_data):32'b0));
        end
      end
      if(rst_n && $past(rst_n && host_valid && !host_ready)) begin
        assume(host_valid);assume({host_kind,host_addr,host_data}==$past({host_kind,host_addr,host_data}));
      end
      cover(rst_n && host_rsp_valid && host_error);
      cover(rst_n && start);
      cover(rst_n && dcr_valid && !dcr_rw);
      cover(rst_n && host_rsp_valid && !host_rsp_ready);
    end
  end
  for(genvar port=0;port<2;port=port+1) begin: ports
    (* anyseq *) reg valid,rw,ready,response_valid,response_ready;
    (* anyseq *) reg [63:0] mask;
    (* anyseq *) reg [25:0] address;
    (* anyseq *) reg [511:0] data,response_data;
    (* anyseq *) reg [9:0] tag,response_tag;
    wire req_ready,req_valid,req_rw,rsp_ready,rsp_valid;
    wire [63:0] req_mask;
    wire [25:0] req_address;
    wire [511:0] req_data,rsp_data;
    wire [9:0] req_tag,rsp_tag;
    vortex_memory_adapter #(.ADDR_WIDTH(26),.DATA_WIDTH(512),.TAG_WIDTH(10)) memory_adapter (
      .clk_i(clk),.rst_ni(rst_n),.vx_req_valid_i(valid),.vx_req_ready_o(req_ready),
      .vx_req_rw_i(rw),.vx_req_byteen_i(mask),.vx_req_addr_i(address),.vx_req_data_i(data),.vx_req_tag_i(tag),
      .vx_rsp_valid_o(rsp_valid),.vx_rsp_ready_i(response_ready),.vx_rsp_data_o(rsp_data),.vx_rsp_tag_o(rsp_tag),
      .mem_req_valid_o(req_valid),.mem_req_ready_i(ready),.mem_req_rw_o(req_rw),.mem_req_byteen_o(req_mask),
      .mem_req_addr_o(req_address),.mem_req_data_o(req_data),.mem_req_tag_o(req_tag),
      .mem_rsp_valid_i(response_valid),.mem_rsp_ready_o(rsp_ready),.mem_rsp_data_i(response_data),.mem_rsp_tag_i(response_tag));
    always @(posedge clk) if(past_valid) begin
      assert(req_ready==(!req_valid || ready));assert(rsp_ready==(!rsp_valid || response_ready));
      if(!$past(rst_n)) begin assert(!req_valid);assert(!rsp_valid);end
      else begin
        if($past(req_ready)) begin
          assert(req_valid==$past(valid));
          if($past(valid)) assert({req_rw,req_mask,req_address,req_data,req_tag}==$past({rw,mask,address,data,tag}));
        end else begin
          assert(req_valid);assert({req_rw,req_mask,req_address,req_data,req_tag}==$past({req_rw,req_mask,req_address,req_data,req_tag}));
        end
        if($past(rsp_ready)) begin
          assert(rsp_valid==$past(response_valid));
          if($past(response_valid)) assert({rsp_data,rsp_tag}==$past({response_data,response_tag}));
        end else begin assert(rsp_valid);assert({rsp_data,rsp_tag}==$past({rsp_data,rsp_tag}));end
      end
      if(rst_n && $past(rst_n)) begin
        if($past(valid && !req_ready)) begin assume(valid);assume({rw,mask,address,data,tag}==$past({rw,mask,address,data,tag}));end
        if($past(response_valid && !rsp_ready)) begin assume(response_valid);assume({response_data,response_tag}==$past({response_data,response_tag}));end
      end
      cover(rst_n && req_valid && !ready);
      cover(rst_n && rsp_valid && !response_ready);
      cover(rst_n && req_valid && ready && valid && req_ready);
      cover(!rst_n && $past(rst_n && req_valid));
    end
  end
endmodule
