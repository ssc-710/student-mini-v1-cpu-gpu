/* Host bridge exercising actual fixed native candidate; target integration pending. */
#include "p3_record_native_eligibility.h"
static bool p3_record_native_dispatch(const uint8_t *p,student_mini_result *r){
 if(!p3_record_native_eligible(p)){p3g_host_reference<true>(p,r);return false;}
 memset(r,0,sizeof(*r));mini_native_model m={};int8_t g[512],u[512],d[512];
 for(unsigned e=0;e<2;++e)for(unsigned k=0;k<16;++k)for(unsigned j=0;j<16;++j){
  g[e*256+k*16+j]=(int8_t)p[400+e*256+j*16+k];
  u[e*256+k*16+j]=(int8_t)p[912+e*256+j*16+k];
  d[e*256+k*16+j]=(int8_t)p[1424+e*256+j*16+k];
 }
 m.weight[MINI_GATE]=g;m.weight[MINI_UP]=u;m.weight[MINI_DOWN]=d;
 m.scale[MINI_GATE]=p3g_real(p,17);m.scale[MINI_UP]=p3g_real(p,18);
 for(unsigned row=0;row<p3g_word(p,4);++row){
  float route=p3g_real(p,23+row);m.scale[MINI_DOWN]=p3g_real(p,20)*(route==0.0f?1.0f:route);
  if(p3_native_candidate_ctx(0,p3g_word(p,14+row),(const int8_t*)p+128+row*16,p3g_real(p,16),&m,r->output+row*16)){r->status=4;r->count=0;return true;}
  if(route==0.0f)memset(r->output+row*16,0,16*sizeof(uint16_t));
 }
 r->count=16*p3g_word(p,4);r->primitive=p3g_primitive(p);return true;
}
