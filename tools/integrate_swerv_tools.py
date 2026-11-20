from pathlib import Path
p=Path(__file__).resolve().parents[1]/'dsh/main-task-tools.mjs'
s=p.read_text(encoding='utf-8')
old="'aes_core_sky130_t'],required:true}"
new="'aes_core_sky130_t','swerv_nangate45'],required:true}"
assert old in s or new in s
s=s.replace(old,new)
note='swerv_nangate45 为本次登记的中规模含宏新案例：6777标准单元+3个研究SRAM硬宏，17阶段full_backend，服务器4核8GB、总预算2小时、布线最多90分钟；首次资格实验尚未验收，流程与DRC质量分别报告，不得扩大预算。'
if note not in s:s=s.replace('三者无硬宏。','三者无硬宏。'+note)
p.write_text(s,encoding='utf-8')
p=p.with_name('desktop-tools.mjs');s=p.read_text(encoding='utf-8')
note='另有 swerv_nangate45：6777个初始标准单元、3个研究用SRAM硬宏；只支持full_backend，17阶段含原生宏布局，总预算7200秒。该案例走明确登记的首次资格试验入口，verified=false不代表已有全流程通过；每阶段仍需真实独立检查，残余DRC单列质量未通过。'
if note not in s:s=s.replace('支持案例包不等于支持任意网表。',note+'支持案例包不等于支持任意网表。')
p.write_text(s,encoding='utf-8')
