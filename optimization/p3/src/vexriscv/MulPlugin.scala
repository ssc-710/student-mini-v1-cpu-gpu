package vexriscv.plugin
import vexriscv._
import vexriscv.VexRiscv
import spinal.core._
import spinal.lib._

//Input buffer generaly avoid the FPGA synthesis to duplicate reg inside the DSP cell, which could stress timings quite much.
class MulPlugin(var inputBuffer : Boolean = false,
                var outputBuffer : Boolean = false) extends Plugin[VexRiscv] with VexRiscvRegressionArg {
  require(!inputBuffer && !outputBuffer, "P3 overlay requires the unbuffered partial-product configuration")
  object MUL_LL extends Stageable(UInt(32 bits))
  object MUL_LH extends Stageable(SInt(34 bits))
  object MUL_HL extends Stageable(SInt(34 bits))
  object MUL_HH extends Stageable(SInt(34 bits))

  object MUL_LOW extends Stageable(SInt(34+16+2 bits))

  object IS_MUL extends Stageable(Bool)
  object IS_P3 extends Stageable(Bool)
  object P3_NEGATIVE extends Stageable(Bool)
  object P3_SHIFT extends Stageable(SInt(6 bits))
  var p3Exception : Flow[ExceptionCause] = null


  override def getVexRiscvRegressionArgs(): Seq[String] = {
    List("MUL=yes")
  }

  override def setup(pipeline: VexRiscv): Unit = {
    import Riscv._
    import pipeline.config._


    val actions = List[(Stageable[_ <: BaseType],Any)](
//      SRC1_CTRL                -> Src1CtrlEnum.RS,
//      SRC2_CTRL                -> Src2CtrlEnum.RS,
      REGFILE_WRITE_VALID      -> True,
      BYPASSABLE_EXECUTE_STAGE -> False,
      BYPASSABLE_MEMORY_STAGE  -> False,
      RS1_USE                 -> True,
      RS2_USE                 -> True,
      IS_MUL                   -> True
    )

    val decoderService = pipeline.service(classOf[DecoderService])
    decoderService.addDefault(IS_MUL, False)
    decoderService.addDefault(IS_P3, False)
    decoderService.add(M"0101010----------000-----0001011", actions :+ (IS_P3 -> True))
    p3Exception = pipeline.service(classOf[ExceptionService]).newExceptionPort(pipeline.execute)

    decoderService.add(List(
      MULX  -> actions
    ))

  }

  override def build(pipeline: VexRiscv): Unit = {
    import pipeline._
    import pipeline.config._


    //Do partial multiplication, four times 16 bits * 16 bits
    execute plug new Area {
      import execute._
      val aSigned,bSigned = Bool
      val a,b = Bits(32 bit)

//      a := input(SRC1)
//      b := input(SRC2)

      val delay = (if(inputBuffer) 1 else 0) + (if(outputBuffer) 1 else 0)

      val delayLogic = (delay != 0) generate new Area{
        val counter = Reg(UInt(log2Up(delay+1) bits))
        when(arbitration.isValid && input(IS_MUL) && counter =/= delay){
          arbitration.haltItself := True
        }

        counter := counter + 1
        when(!arbitration.isStuck || arbitration.isStuckByOthers){
          counter := 0
        }
      }

      val withInputBuffer = inputBuffer generate new Area{
        val rs1 = RegNext(input(RS1))
        val rs2 = RegNext(input(RS2))
        a := rs1
        b := rs2
      }

      val noInputBuffer = (!inputBuffer) generate new Area{
        a := input(RS1)
        b := input(RS2)
      }

      val p3Prepared = RegInit(False)
      val p3Magnitude = Reg(Bits(32 bits))
      val p3Significand = Reg(Bits(32 bits))
      val p3Negative = Reg(Bool)
      val p3Shift = Reg(SInt(6 bits))
      val p3Owner = arbitration.isValid && input(IS_P3)
      val contextShift = input(RS2)(29 downto 24).asSInt
      val contextLegal = input(RS2)(31 downto 30) === B"00" &&
        contextShift >= S(-28, 6 bits) && contextShift <= S(4, 6 bits)
      p3Exception.valid := p3Owner && !contextLegal
      p3Exception.valid clearWhen(service(classOf[HazardService]).hazardOnExecuteRS)
      p3Exception.code := 2
      p3Exception.badAddr := input(INSTRUCTION).asUInt
      when(p3Owner && contextLegal && !p3Prepared && !arbitration.isRemoved) {
        arbitration.haltItself := True
        p3Magnitude := Mux(input(RS1).msb, (U(0, 32 bits) - input(RS1).asUInt).asBits, input(RS1))
        p3Significand := B(0, 8 bits) ## input(RS2)(23 downto 0)
        p3Negative := input(RS1).msb
        p3Shift := contextShift
        p3Prepared := True
      }
      when(!p3Owner || arbitration.isRemoved || arbitration.isFiring) {
        p3Prepared := False
      }
      insert(P3_NEGATIVE) := p3Negative
      insert(P3_SHIFT) := p3Shift
      when(input(IS_P3)) {
        a := p3Magnitude
        b := p3Significand
      }

      switch(input(INSTRUCTION)(13 downto 12)) {
        is(B"01") {
          aSigned := True
          bSigned := True
        }
        is(B"10") {
          aSigned := True
          bSigned := False
        }
        default {
          aSigned := False
          bSigned := False
        }
      }

      when(input(IS_P3)) {
        aSigned := False
        bSigned := False
      }

      val aULow = a(15 downto 0).asUInt
      val bULow = b(15 downto 0).asUInt
      val aSLow = (False ## a(15 downto 0)).asSInt
      val bSLow = (False ## b(15 downto 0)).asSInt
      val aHigh = (((aSigned && a.msb) ## a(31 downto 16))).asSInt
      val bHigh = (((bSigned && b.msb) ## b(31 downto 16))).asSInt

      val withOuputBuffer = outputBuffer generate new Area{
        val mul_ll = RegNext(aULow * bULow)
        val mul_lh = RegNext(aSLow * bHigh)
        val mul_hl = RegNext(aHigh * bSLow)
        val mul_hh = RegNext(aHigh * bHigh)

        insert(MUL_LL) := mul_ll
        insert(MUL_LH) := mul_lh
        insert(MUL_HL) := mul_hl
        insert(MUL_HH) := mul_hh
      }

      val noOutputBuffer = (!outputBuffer) generate new Area{
        insert(MUL_LL) := aULow * bULow
        insert(MUL_LH) := aSLow * bHigh
        insert(MUL_HL) := aHigh * bSLow
        insert(MUL_HH) := aHigh * bHigh
      }

      Component.current.afterElaboration{
        //Avoid synthesis tools to retime RS1 RS2 from execute stage to decode stage leading to bad timings (ex : Vivado, even if retiming is disabled)
        KeepAttribute(input(RS1))
        KeepAttribute(input(RS2))
      }
    }

    //First aggregation of partial multiplication
    memory plug new Area {
      import memory._
      insert(MUL_LOW) := S(0, MUL_HL.dataType.getWidth + 16 + 2 bit) + (False ## input(MUL_LL)).asSInt + (input(MUL_LH) << 16) + (input(MUL_HL) << 16)
    }

    //Final aggregation of partial multiplications, REGFILE_WRITE_DATA overriding
    writeBack plug new Area {
      import writeBack._
      val result = input(MUL_LOW) + (input(MUL_HH) << 32)
      val p3Owner = arbitration.isValid && input(IS_P3)
      val p3Launched = RegInit(False)
      val finish = new P3ScaleFinish
      finish.io.flush := !p3Owner || arbitration.isRemoved
      finish.io.input_valid := p3Owner && !p3Launched && !arbitration.isRemoved
      finish.io.input_product := result.asBits(55 downto 0).asUInt
      finish.io.input_negative := input(P3_NEGATIVE)
      finish.io.input_shift := input(P3_SHIFT)
      finish.io.input_rd := input(INSTRUCTION)(11 downto 7).asUInt
      finish.io.output_ready := p3Owner && arbitration.isFiring && !arbitration.isRemoved
      when(finish.io.input_valid && finish.io.input_ready) { p3Launched := True }
      when(!p3Owner || arbitration.isRemoved || arbitration.isFiring) { p3Launched := False }
      when(p3Owner && !arbitration.isRemoved) {
        when(!finish.io.output_valid) { arbitration.haltItself := True }
        output(REGFILE_WRITE_DATA) := finish.io.output_result.resize(32).asBits
      }



      when(arbitration.isValid && input(IS_MUL) && !input(IS_P3)){
        switch(input(INSTRUCTION)(13 downto 12)){
          is(B"00"){
            output(REGFILE_WRITE_DATA) := input(MUL_LOW)(31 downto 0).asBits
          }
          is(B"01",B"10",B"11"){
            output(REGFILE_WRITE_DATA) := result(63 downto 32).asBits
          }
        }
      }
    }
  }
}

class P3ScaleFinish extends BlackBox {
  setDefinitionName("cpu_p3_scale_finish_elastic")
  val io = new Bundle {
    val clk, reset, flush = in Bool()
    val input_ready = out Bool()
    val input_valid, input_negative = in Bool()
    val input_product = in UInt(56 bits)
    val input_shift = in SInt(6 bits)
    val input_rd = in UInt(5 bits)
    val output_ready = in Bool()
    val output_valid = out Bool()
    val output_result = out SInt(16 bits)
    val output_rd = out UInt(5 bits)
  }
  noIoPrefix()
  mapClockDomain(clock=io.clk, reset=io.reset)
}
