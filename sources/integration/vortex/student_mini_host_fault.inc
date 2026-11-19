// SPDX-License-Identifier: Apache-2.0
// Included after the generated device-only mini scalar implementation.
// Bus-fault variant: status-6 records perform one load from the unmapped window.
__global__ void student_mini_kernel(const uint16_t *exp_lut,const int16_t *silu_lut,
                                  const uint8_t *input,student_mini_result *output) {
    if(threadIdx.x)return;
    gpu_exp_lut_device=exp_lut;gpu_silu_lut_device=silu_lut;
    student_mini_execute(input+blockIdx.x*STUDENT_MINI_RECORD_BYTES,output+blockIdx.x);
    // Status 6 = the case requires a device bus fault. Issue one real load
    // from the reserved unmapped window 0xE0000000; the external memory system
    // answers with a bus error that the memory adapter latches in the device
    // status register (DCR 0xFFF). The kernel itself never claims BUS_ERROR.
    if(output[blockIdx.x].status==6) {
        volatile const uint32_t *fault=(volatile const uint32_t *)(uintptr_t)0xE0000000u;
        output[blockIdx.x].primitive=(int32_t)(*fault&0u);
    }
}
static void mini_check(cudaError_t code,const char *where) {
    if(code!=cudaSuccess){fprintf(stderr,"%s: %s\n",where,cudaGetErrorString(code));exit(2);}
}
template<class T> static T *mini_copy(const T *source,size_t count) {
    T *device=nullptr;
    mini_check(cudaMalloc(&device,count*sizeof(T)),"allocate");
    mini_check(cudaMemcpy(device,source,count*sizeof(T),cudaMemcpyHostToDevice),"copy input");
    return device;
}
int main(int argc,char **argv) {
    if(argc<2){fprintf(stderr,"usage: student_mini inputs.bin [start] [count]\n");return 2;}
    FILE *file=fopen(argv[1],"rb");if(!file)return 2;
    fseek(file,0,SEEK_END);long length=ftell(file);rewind(file);
    if(length<=0 || length%STUDENT_MINI_RECORD_BYTES)return 2;
    unsigned total=length/STUDENT_MINI_RECORD_BYTES;
    unsigned start=argc>2?strtoul(argv[2],nullptr,10):0,count=argc>3?strtoul(argv[3],nullptr,10):total;
    if(!count || start>=total || count>total-start)return 2;
    uint8_t *input=(uint8_t *)malloc(count*STUDENT_MINI_RECORD_BYTES);
    fseek(file,start*STUDENT_MINI_RECORD_BYTES,SEEK_SET);
    if(fread(input,STUDENT_MINI_RECORD_BYTES,count,file)!=count)return 2;
    fclose(file);
    auto exp=mini_copy(course_exp_q15_q6_lut,1025);auto silu=mini_copy(course_silu_q11_q6_lut,2049);
    auto device_input=mini_copy(input,count*STUDENT_MINI_RECORD_BYTES);
    student_mini_result *device_output=nullptr;
    mini_check(cudaMalloc(&device_output,count*sizeof(student_mini_result)),"allocate output");
    // One launch per process: the locked command processor's multi-launch
    // issue must not be hidden by replaying results on the host.
    student_mini_kernel<<<count,1>>>(exp,silu,device_input,device_output);
    mini_check(cudaGetLastError(),"launch");mini_check(cudaDeviceSynchronize(),"synchronize");
    auto output=(student_mini_result *)calloc(count,sizeof(student_mini_result));
    mini_check(cudaMemcpy(output,device_output,count*sizeof(student_mini_result),cudaMemcpyDeviceToHost),"copy actual");
    for(unsigned i=0;i<count;++i) {
        const auto &r=output[i];if(r.count>32 || r.selected_count>8)return 3;
        printf("STUDENT_GPU ordinal=%u status=%u primitive=%d bits=",start+i,r.status,r.primitive);
        for(unsigned j=0;j<r.count;++j)printf("%s%04x",j?",":"",r.output[j]);
        printf(" selected=");for(unsigned j=0;j<r.selected_count;++j)printf("%s%u",j?",":"",r.selected[j]);
        printf("\n");
    }
    printf("STUDENT_GPU_COMPLETE start=%u count=%u\n",start,count);fflush(stdout);
    cudaFree(exp);cudaFree(silu);cudaFree(device_input);cudaFree(device_output);free(input);free(output);
    return 0;
}
