// SPDX-License-Identifier: Apache-2.0
// One real device launch computes the complete autoregressive session.
__global__ void native_nano_kernel(const uint16_t *exp_lut,const int16_t *silu_lut,
    const uint8_t *image,mini_native_result *result,int *status) {
    if(threadIdx.x || blockIdx.x)return;
    gpu_exp_lut_device=exp_lut;gpu_silu_lut_device=silu_lut;
    mini_native_model model;
    const float *scales=(const float *)(image+COURSE_NANO_SEGMENT_SCALES_FP32_OFFSET);
    // __NATIVE_MODEL_BINDINGS__
    *status=mini_native_generate(&model,(const uint32_t *)(image+COURSE_NANO_SEGMENT_PROMPT_TOKENS_U32_OFFSET),COURSE_NANO_PROMPT_TOKENS,nullptr,result);
}
static void native_check(cudaError_t code,const char *where) {
    if(code!=cudaSuccess){fprintf(stderr,"%s: %s\n",where,cudaGetErrorString(code));exit(2);}
}
template<class T> static T *native_copy(const T *source,size_t count) {
    T *device=nullptr;
    native_check(cudaMalloc(&device,count*sizeof(T)),"allocate");
    native_check(cudaMemcpy(device,source,count*sizeof(T),cudaMemcpyHostToDevice),"copy input");
    return device;
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    FILE *file=fopen(argv[1],"rb");if(!file)return 2;
    fseek(file,0,SEEK_END);long length=ftell(file);rewind(file);
    if(length!=COURSE_NATIVE_IMAGE_BYTES)return 2;
    auto input=(uint8_t *)malloc(length);
    if(!input || fread(input,1,length,file)!=(size_t)length)return 2;
    fclose(file);
    auto exp=native_copy(course_exp_q15_q6_lut,1025);
    auto silu=native_copy(course_silu_q11_q6_lut,2049);
    auto device_input=native_copy(input,(size_t)length);
    mini_native_result *device_result=nullptr;
    int initial=-99;auto device_status=native_copy(&initial,1);
    native_check(cudaMalloc(&device_result,sizeof(mini_native_result)),"allocate result");
    native_nano_kernel<<<1,1>>>(exp,silu,device_input,device_result,device_status);
    native_check(cudaGetLastError(),"launch");native_check(cudaDeviceSynchronize(),"synchronize");
    auto result=(mini_native_result *)calloc(1,sizeof(mini_native_result));
    native_check(cudaMemcpy(result,device_result,sizeof(*result),cudaMemcpyDeviceToHost),"read result");
    int status=-99;
    native_check(cudaMemcpy(&status,device_status,sizeof(status),cudaMemcpyDeviceToHost),"read status");
    printf("STUDENT_NATIVE_GPU status=%d count=%u\n",status,result->count);
    if(status || !result->count || result->count>12)return 3;
    for(unsigned step=0;step<result->count;++step) {
        printf("STUDENT_NATIVE_TOKEN step=%u token=%u hidden=",step,result->tokens[step]);
        for(unsigned j=0;j<16;++j)printf("%s%04x",j?",":"",result->final_hidden[step][j]);
        printf(" logits=");
        for(unsigned j=0;j<256;++j)printf("%s%04x",j?",":"",result->logits[step][j]);
        printf("\n");
    }
    printf("STUDENT_NATIVE_GPU_COMPLETE count=%u p1=%u p2=%u p3=%u\n",result->count,result->p1_calls,result->p2_calls,result->p3_calls);
    fflush(stdout);
    cudaFree(exp);cudaFree(silu);cudaFree(device_input);cudaFree(device_result);cudaFree(device_status);
    free(input);free(result);
    return 0;
}
