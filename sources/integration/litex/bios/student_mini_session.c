// SPDX-License-Identifier: Apache-2.0
#include <stdint.h>
#include <stdio.h>
#include <generated/csr.h>
#include <generated/soc.h>
#include <generated/mem.h>
#include "init.h"
#include "../../../software/include/student_mini_scalar.h"

static uint64_t counter(unsigned instructions) {
    uint32_t hi,lo,again;
    do {
        if(instructions){
            __asm__ volatile("csrr %0, minstreth":"=r"(hi));
            __asm__ volatile("csrr %0, minstret":"=r"(lo));
            __asm__ volatile("csrr %0, minstreth":"=r"(again));
        } else {
            __asm__ volatile("csrr %0, mcycleh":"=r"(hi));
            __asm__ volatile("csrr %0, mcycle":"=r"(lo));
            __asm__ volatile("csrr %0, mcycleh":"=r"(again));
        }
    } while(hi!=again);
    return ((uint64_t)hi<<32)|lo;
}
static void print64(uint64_t n) {
    printf("%lu:%lu",(unsigned long)(n>>32),(unsigned long)n);
}
static unsigned dma_command(unsigned opcode,unsigned inject_fault) {
    volatile uint32_t *d=(volatile uint32_t *)(COURSE_UNCACHED_DRAM_BASE+0x200000u);
    for(unsigned i=0;i<16;++i)d[i]=0;
    d[0]=1u|(opcode<<8);d[1]=1;d[2]=1;d[3]=1;
    volatile uint32_t *csr=(volatile uint32_t *)ACCELERATOR_BASE;
    csr[1]=opcode;
    csr[2]=inject_fault?0x30000000u:MAIN_RAM_BASE+0x200000u;
    csr[0]=1;
    for(unsigned wait=0;wait<1000000;++wait)if(csr[0]&2u) {
        unsigned status=csr[4];csr[3]=1;return status;
    }
    return 255;
}
static void student_mini_session(void) {
#ifdef COURSE_STUDENT_MINI_COUNT
    cpu_traffic_reset_write(1);cpu_traffic_reset_write(0);
    unsigned probe_status=dma_command(1,0);
    cpu_traffic_capture_write(1);cpu_traffic_capture_write(0);
    printf("STUDENT_CPU_DMA_PROBE status=%u bytes=",probe_status);print64(cpu_traffic_dma_bytes_read());printf("\n");
    printf("STUDENT_CPU_BEGIN count=%u record_bytes=%u\n",COURSE_STUDENT_MINI_COUNT,STUDENT_MINI_RECORD_BYTES);
    for(unsigned i=0;i<COURSE_STUDENT_MINI_COUNT;++i) {
        const uint8_t *p=(const uint8_t *)(MAIN_RAM_BASE+i*STUDENT_MINI_RECORD_BYTES);
        student_mini_result result;
        cpu_traffic_reset_write(1);cpu_traffic_reset_write(0);
        uint64_t start=counter(0),inst=counter(1);
        student_mini_execute(p,&result);
        if(result.status==6)result.status=dma_command(((const uint32_t *)p)[1],1);
        uint64_t elapsed=counter(0)-start,instructions=counter(1)-inst;
        cpu_traffic_capture_write(1);cpu_traffic_capture_write(0);
        uint64_t ibus=cpu_traffic_ibus_bytes_read(),dbus=cpu_traffic_dbus_bytes_read(),dma=cpu_traffic_dma_bytes_read();
        printf("STUDENT_CPU ordinal=%u status=%lu cycles=",i,(unsigned long)result.status);print64(elapsed);
        printf(" instructions=");print64(instructions);
        printf(" ibus_bytes=");print64(ibus);printf(" dbus_bytes=");print64(dbus);
        printf(" dma_bytes=");print64(dma);
        printf(" primitive=%ld bits=",(long)result.primitive);
        for(unsigned j=0;j<result.count;++j)printf("%s%04x",j?",":"",result.output[j]);
        printf(" selected=");
        for(unsigned j=0;j<result.selected_count;++j)printf("%s%u",j?",":"",result.selected[j]);
        printf("\n");
    }
    printf("STUDENT_CPU_COMPLETE count=%u\n",COURSE_STUDENT_MINI_COUNT);
#endif
}
define_init_func(student_mini_session);
