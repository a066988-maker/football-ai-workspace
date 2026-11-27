'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');

const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const script=html.split('<script>').at(-1).split('</script>')[0];
new vm.Script(script);
const copy=script.slice(script.indexOf('function makeCopy('),script.indexOf('function make(){'));
const assets=script.slice(script.indexOf("const repo='"),script.indexOf('function clearStaleOutput'));
const now='2026-11-27T02:30:00+08:00';
const sha='a'.repeat(40);
const approved={status:'analysis_ready_rules',window_start:'2026-11-26T16:00+08:00',
  github_run_id:'101',quality:{publish_allowed:true},assets:['poster.png','xiaohongshu.txt']};
const goodQa={status:'passed',publish_allowed:true,github_run_id:'101'};
function harness(status,qa=goodQa){
  const requests=[];
  const fetch=async url=>{
    requests.push(url);
    const data=url.includes('/git/ref/')?{object:{sha}}:url.includes('status.json')?status:qa;
    return {ok:true,json:async()=>data,text:async()=>'archive sample',blob:async()=>new Blob(['archive sample'])};
  };
  const code=assets+'\n;({automaticAsset,canUseAutomaticAssets})';
  const DateAt=class extends Date{constructor(value){super(value??now)} static now(){return Date.parse(now)}};
  return {...vm.runInNewContext(code,{fetch,Date:DateAt}),requests};
}
test('blocked or stale status cannot expose reachable old PNG or TXT',async()=>{
  for(const status of [{...approved,status:'insufficient_verified_odds'},{...approved,window_start:'2026-11-25T16:00+08:00'}]){
    const h=harness(status);
    await assert.rejects(h.automaticAsset('poster.png'),/尚無通過驗收/);
    await assert.rejects(h.automaticAsset('xiaohongshu.txt'),/尚無通過驗收/);
    assert.ok(!h.requests.some(x=>x.includes('poster.png')||x.includes('xiaohongshu.txt')));
  }
});
test('verified overnight download pins QA and asset to the same commit',async()=>{
  const h=harness(approved);
  assert.equal(await (await h.automaticAsset('xiaohongshu.txt')).text(),'archive sample');
  assert.equal(h.requests.length,4);
  for(const url of h.requests.slice(1))assert.ok(url.includes('/'+sha+'/output/'));
  const mismatched=harness(approved,{...goodQa,github_run_id:'100'});
  await assert.rejects(mismatched.automaticAsset('poster.png'),/不符/);
  assert.ok(!mismatched.requests.some(x=>x.includes('poster.png')));
});
test('a match correction rebuilds one full post with disclaimer and tags',()=>{
  const makeCopy=vm.runInNewContext(copy+'\nmakeCopy');
  const matches=Array.from({length:4},(_,i)=>({home:'主队'+i,away:'客队'+i,league:'联赛',
    kickoff:'2026-11-27T04:00+08:00',analysis:'赛前观察'+i,trend:'大 2.5',scores:['2-1','3-1','2-2']}));
  matches[0].analysis='更正后第一场分析';
  const caption=makeCopy({matches,source:'AiScore public',analysis_engine:'rules_fallback'});
  for(const fragment of ['主队0迎战客队0','先看盘口变化','更正后第一场分析','赛前观察3','趋势：大 2.5',
    '比分：2-1 / 3-1 / 2-2','盘口来源：AiScore','不构成投注建议','#足球 #足球分析 #赛事前瞻'])
    assert.ok(caption.includes(fragment),fragment);
  assert.ok(!caption.includes('赛前观察0'));
});
