/* Frozen-record bridge eligibility; caller retains layout/routing adaptation. */
#ifndef P3_RECORD_NATIVE_ELIGIBILITY_H
#define P3_RECORD_NATIVE_ELIGIBILITY_H
static bool p3_record_native_eligible(const uint8_t *p) {
    if(p3g_validate(p))return false;
    if(p3g_real(p,19)!=0x1p-6f)return false;
    for(unsigned r=0;r<p3g_word(p,4);++r) {
        float route=p3g_real(p,23+r);
        if(route!=0.0f && route!=0.5f && route!=1.0f)return false;
    }
    return true;
}
#endif
