// Start a disposable Chrome instance with remote debugging on loopback.
// node probe.mjs http://127.0.0.1:9229
import assert from "node:assert/strict";
const base = process.argv[2];
async function openPage() {
  const tab = await (await fetch(base + "/json/new?about:blank", {method:"PUT"})).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener("open", resolve));
  return async expression => {
    const response = new Promise(resolve => ws.addEventListener("message", e => resolve(JSON.parse(e.data)), {once:true}));
    ws.send(JSON.stringify({id:1,method:"Runtime.evaluate",params:{expression,awaitPromise:true,returnByValue:true}}));
    const {result} = await response;
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    ws.close();
    return result.result.value;
  };
}
const record = await openPage();
const packet = await record(`(async()=>{
  const ctx=new AudioContext(); await ctx.resume();
  const osc=ctx.createOscillator(), dest=ctx.createMediaStreamDestination();
  osc.connect(dest); osc.start();
  const recorder=new MediaRecorder(dest.stream), chunks=[], points=[];
  const start=performance.now();
  recorder.ondataavailable=e=>chunks.push(e.data);
  const stopped=new Promise(resolve=>recorder.onstop=resolve);
  recorder.start();
  for(const x of [40,200]) {
    await new Promise(r=>setTimeout(r,200));
    points.push({ms:Math.round(performance.now()-start),x});
  }
  await new Promise(r=>setTimeout(r,350));
  recorder.stop(); await stopped; osc.stop(); await ctx.close();
  const blob=new Blob(chunks,{type:recorder.mimeType}), reader=new FileReader();
  const loaded=new Promise(r=>reader.onload=r);reader.readAsDataURL(blob);await loaded;
  return {audio:reader.result,points,bytes:blob.size};
})()`);
const play = await openPage();
const result = await play(`(async packet=>{
  const audio=new Audio(packet.audio), observed=[];
  const timer=setInterval(()=>{
    const point=packet.points[observed.length];
    if(point && audio.currentTime*1000>=point.ms) observed.push({x:point.x,lagMs:Math.round(audio.currentTime*1000-point.ms)});
  },10);
  const ended=new Promise((resolve,reject)=>{audio.onended=resolve;audio.onerror=reject;});
  await audio.play();await ended;clearInterval(timer);
  return {bytes:packet.bytes,points:packet.points,observed};
})(`+JSON.stringify(packet)+")");
assert.ok(result.bytes>0);
assert.deepEqual(result.observed.map(x=>x.x),[40,200]);
console.log(JSON.stringify(result,null,2));
