/* No server, credentials or network. Run: node --test portal/tests/security.test.cjs
 * Actual route/action modules are transpiled; only framework and DB boundaries
 * are replaced. SQL concurrency/RLS is tested separately against PostgreSQL. */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const ACTIVE_TOKEN = 'a'.repeat(64);
const ORIGIN = 'https://openreef.example.invalid';

function harness(env = {}) {
  const state = { testers: [], signups: [], feedback: [], announcements: [], rpcs: [], changes: [], rates: new Map(), owner: true, rateError: false, redeemError: false, revalidations: [] };
  const fakeEnv = { SITE_ORIGIN: ORIGIN, ...env };
  class NextResponse extends Response {
    static json(value, options) { return Response.json(value, options); }
    static redirect(url) { return new Response(null, { status: 307, headers: { Location: String(url) } }); }
  }
  const tables = () => ({ beta_testers: state.testers, beta_signups: state.signups, beta_feedback: state.feedback, beta_announcements: state.announcements, beta_feedback_events: [] });
  function serviceClient() {
    return {
      from(table) {
        let operation = 'select', patch, predicates = [], result;
        const chain = {
          select() { return chain; },
          eq(k,v) { predicates.push(row => row[k] === v); return chain; },
          in(k,values) { predicates.push(row => values.includes(row[k])); return chain; },
          not(k,_op,v) { predicates.push(row => row[k] !== v); return chain; },
          order() { return chain; }, limit() { return chain; },
          insert(p) { operation='insert'; patch=p; return chain; },
          update(p) { operation='update'; patch=p; return chain; },
          upsert(p) { operation='upsert'; patch=p; return chain; },
          async single() { const r=execute(); return {...r, data:r.data?.[0] ?? null}; },
          async maybeSingle() { return chain.single(); },
          then(resolve,reject) { return Promise.resolve(execute()).then(resolve,reject); },
        };
        function execute() {
          if (result) return result;
          const rows = tables()[table];
          assert.ok(rows, `Unexpected table ${table}`);
          let chosen = rows.filter(row => predicates.every(predicate => predicate(row)));
          if (operation === 'insert' || operation === 'upsert') {
            const row = { id: `synthetic-${rows.length}`, status:'invited', ref:'OR-SYNTHETIC', ...patch };
            rows.push(row); chosen=[row];
          }
          if (operation === 'update') chosen.forEach(row => Object.assign(row,patch));
          if (operation !== 'select') state.changes.push({table,operation,patch});
          return result={ data:chosen.map(row=>({...row})), error:null };
        }
        return chain;
      },
      async rpc(name,args) {
        state.rpcs.push({name,args});
        if (name === 'beta_take_rate_limit') {
          if (state.rateError) return {data:null,error:{message:'synthetic DB unavailable'}};
          const hits=state.rates.get(args.p_key) ?? 0;
          if (hits>=args.p_limit) return {data:false,error:null};
          state.rates.set(args.p_key,hits+1);
          return {data:true,error:null};
        }
        assert.equal(name,'beta_redeem_invite');
        if(state.redeemError) return {data:null,error:{message:'synthetic migration missing'}};
        const tester=state.testers.find(row => row.invite_hash===args.p_invite_hash && ['invited','active'].includes(row.status) && Date.parse(row.invite_expires_at)>Date.now());
        if(!tester) return {data:[],error:null};
        Object.assign(tester,{status:'active',token_hash:args.p_token_hash,invite_hash:null,invite_expires_at:null});
        return {data:[{tester_name:tester.name}],error:null};
      },
    };
  }
  const cache = new Map();
  function load(relative) {
    relative=relative.replace(/\.ts$/, '');
    if(cache.has(relative)) return cache.get(relative);
    const filename=path.join(root,`${relative}.ts`);
    const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    const mod={exports:{}};
    const mockRequire=id=>{
      if(id==='server-only') return {};
      if(id==='node:net') return require(id);
      if(id==='next/server') return {NextResponse};
      if(id==='next/cache') return {revalidatePath:p=>state.revalidations.push(p)};
      if(id==='next/navigation') return {redirect:()=>{throw new Error('redirect');}};
      if(id==='@/lib/auth') return {
        requireOwner:async()=>{if(!state.owner) throw new Error('owner required'); return {id:'owner'};},
        isOwnerEmail:email=>email==='owner@example.invalid',
      };
      if(id.endsWith('/supabase')) return {serviceClient,sessionClient:async()=>({auth:{exchangeCodeForSession:async()=>({data:{user:{email:'owner@example.invalid'}},error:null}),signOut:async()=>{}}})};
      if(id.startsWith('@/')) return load(id.slice(2));
      if(id.startsWith('./')) return load(path.posix.join(path.posix.dirname(relative),id));
      throw new Error(`Unexpected import ${id}`);
    };
    vm.runInNewContext(`(function(require,module,exports){${code}\n})`,{Request,Response,URL,TextEncoder,TextDecoder,Uint8Array,crypto:webcrypto,Date,process:{env:fakeEnv}}, {filename})(mockRequire,mod,mod.exports);
    cache.set(relative,mod.exports);return mod.exports;
  }
  return {state,load};
}
function request(route,body,headers={}) {
  return new Request(`https://portal.example.invalid/${route}`,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(body)});
}
function form(values) {const f=new FormData();for(const [k,v] of Object.entries(values))f.set(k,v);return f;}
async function seed(h,status='active') {
  const api=h.load('lib/api');
  const code=api.newInviteCode();
  const tester={id:'tester-1',name:'Synthetic tester',status,token_hash:await api.hashToken(ACTIVE_TOKEN),invite_hash:await api.hashToken(code),invite_expires_at:new Date(Date.now()+60_000).toISOString()};
  h.state.testers.push(tester);return {code,tester};
}

test('invitations have 128 random bits and remain within existing HA length limit',()=>{
  const h=harness();const api=h.load('lib/api');const seen=new Set();
  for(let i=0;i<100;i++){const code=api.newInviteCode();assert.match(code,/^REEF-[A-F0-9]{32}$/);assert.equal(code.length,37);seen.add(code);}
  assert.equal(seen.size,100);
});

test('bounded JSON rejects streamed and declared oversized bodies before parsing',async()=>{
  const {readJson}=harness().load('lib/api');
  assert.equal((await readJson(request('api/enrol',{x:'x'.repeat(80)}),32)).error.status,413);
  assert.equal((await readJson(request('api/enrol',{}, {'Content-Length':'9999'}),32)).error.status,413);
  let cancelled=false;
  const body=new ReadableStream({pull(controller){controller.enqueue(new Uint8Array(20));},cancel(){cancelled=true;}});
  const streamed=new Request('https://example.invalid',{method:'POST',headers:{'Content-Type':'application/json'},body,duplex:'half'});
  assert.equal((await readJson(streamed,32)).error.status,413);assert.equal(cancelled,true);
  assert.equal((await readJson(request('api/enrol',[]))).error.status,400);
  assert.equal((await readJson(request('api/enrol',{}, {'Content-Type':'text/plain'}))).error.status,415);
  assert.equal((await readJson(request('api/enrol',{x:'é'.repeat(20)}),32)).error.status,413);
  assert.equal((await readJson(request('api/enrol',{ok:true}))).body.ok,true);
});

test('one-time enrolment hashes code, replaces token once, refuses replay and legacy codes',async()=>{
  const h=harness();const {code,tester}=await seed(h);const route=h.load('app/api/enrol/route');
  const first=await route.POST(request('api/enrol',{code:code.toLowerCase(),agreementAccepted:true}));
  assert.equal(first.status,200);assert.equal(first.headers.get('cache-control'),'no-store');
  const result=await first.json();assert.match(result.token,/^[a-f0-9]{64}$/);
  assert.equal(tester.token_hash,await h.load('lib/api').hashToken(result.token));
  const saved=tester.token_hash;
  assert.equal((await route.POST(request('api/enrol',{code,agreementAccepted:true}))).status,403);
  assert.equal(tester.token_hash,saved);
  assert.equal((await route.POST(request('api/enrol',{code:'REEF-BCDF',agreementAccepted:true}))).status,403);
  assert.ok(!JSON.stringify(h.state.rpcs).includes(code));
});

test('expired, paused and revoked invitations cannot enroll; agreement is mandatory',async()=>{
  for(const status of ['paused','revoked','active']) {
    const h=harness();const {code,tester}=await seed(h,status);const original=tester.token_hash;
    if(status==='active') tester.invite_expires_at=new Date(Date.now()-1000).toISOString();
    assert.equal((await h.load('app/api/enrol/route').POST(request('api/enrol',{code,agreementAccepted:true}))).status,403);
    assert.equal(tester.status,status);assert.equal(tester.token_hash,original);
  }
  const h=harness();const {code}=await seed(h);
  assert.equal((await h.load('app/api/enrol/route').POST(request('api/enrol',{code}))).status,403);
  assert.equal(h.state.rpcs.filter(x=>x.name==='beta_redeem_invite').length,0);
});

test('limiter fails closed across all public write routes if its migration or DB is unavailable',async()=>{
  for(const endpoint of ['signup','enrol','feedback','sync']) {
    const h=harness();h.state.rateError=true;
    const response=await h.load(`app/api/${endpoint}/route`).POST(request(`api/${endpoint}`,{}, {Origin:ORIGIN}));
    assert.equal(response.status,503,endpoint);assert.equal(h.state.changes.length,0);
  }
  const h=harness();const {code}=await seed(h);h.state.redeemError=true;
  assert.equal((await h.load('app/api/enrol/route').POST(request('api/enrol',{code,agreementAccepted:true}))).status,503);
});

test('rate keys cannot be evaded with untrusted forwarding headers and limits return retry advice',async()=>{
  const h=harness();const rate=h.load('lib/rate-limit');
  assert.equal(rate.clientAddress(request('x',{}, {'x-forwarded-for':'192.0.2.1','x-vercel-forwarded-for':'192.0.2.2'})),'shared');
  const vercel=harness({VERCEL:'1'}).load('lib/rate-limit');
  assert.equal(vercel.clientAddress(request('x',{}, {'x-vercel-forwarded-for':'192.0.2.2'})),'192.0.2.2');
  assert.equal(vercel.clientAddress(request('x',{}, {'x-vercel-forwarded-for':'spoof, 192.0.2.2'})),'shared');
  for(let i=0;i<10;i++)assert.equal(await rate.limitRequest(request('x',{}),'signup'),null);
  const denied=await rate.limitRequest(request('x',{}, {'x-forwarded-for':'198.51.100.9'}),'signup');
  assert.equal(denied.status,429);assert.equal(denied.headers.get('retry-after'),'3600');
});

test('signup rejects missing/foreign Origin and hides honeypot submissions without writing',async()=>{
  const h=harness();const route=h.load('app/api/signup/route');
  for(const origin of ['', 'https://evil.example.invalid']) {
    assert.equal((await route.POST(request('api/signup',{email:'test@example.invalid'},{Origin:origin}))).status,403);
    assert.equal(route.OPTIONS(request('api/signup',{}, {Origin:origin})).status,403);
  }
  const bot=await route.POST(request('api/signup',{email:'test@example.invalid',website:'https://spam.example.invalid'},{Origin:ORIGIN}));
  assert.equal(bot.status,200);assert.equal(h.state.signups.length,0);
  const good=await route.POST(request('api/signup',{email:'test@example.invalid'},{Origin:ORIGIN}));
  assert.equal(good.status,200);assert.equal(good.headers.get('access-control-allow-origin'),ORIGIN);assert.equal(h.state.signups.length,1);
});

test('existing active bearer tokens remain valid; paused tokens and malformed tokens are rejected',async()=>{
  const h=harness();const {tester}=await seed(h);const api=h.load('lib/api');
  assert.equal((await api.authenticate(request('api/sync',{}, {Authorization:`Bearer ${ACTIVE_TOKEN}`}))).tester.id,tester.id);
  tester.status='paused';assert.equal((await api.authenticate(request('api/sync',{}, {Authorization:`Bearer ${ACTIVE_TOKEN}`}))).error.status,403);
  assert.equal((await api.authenticate(request('api/sync',{}, {Authorization:'Bearer malformed'}))).error.status,401);
});

test('feedback and sync use authenticated identity and enforce per-tester quotas',async()=>{
  const h=harness();await seed(h);const headers={Authorization:`Bearer ${ACTIVE_TOKEN}`};
  const feedback=h.load('app/api/feedback/route');
  for(let i=0;i<30;i++) assert.equal((await feedback.POST(request('api/feedback',{body:'synthetic',tester_id:'someone-else'},headers))).status,200);
  assert.equal((await feedback.POST(request('api/feedback',{body:'over quota'},headers))).status,429);
  assert.ok(h.state.feedback.every(row=>row.tester_id==='tester-1'));
  const sync=h.load('app/api/sync/route');
  const cap=await h.load('lib/api').hashToken('sync:tester:tester-1');h.state.rates.set(cap,120);
  assert.equal((await sync.POST(request('api/sync',{},headers))).status,429);
});

test('owner invitation actions only persist hashes and do not disrupt current tokens',async()=>{
  const h=harness();const actions=h.load('app/actions');
  const created=await actions.createTester({},form({name:'New tester',email:'new@example.invalid'}));
  assert.match(created.code,/^REEF-[A-F0-9]{32}$/);assert.equal(h.state.testers[0].invite_hash,await h.load('lib/api').hashToken(created.code));
  assert.ok(!JSON.stringify(h.state.changes).includes(created.code));
  assert.ok(Date.parse(created.expiresAt)>Date.now()+6*86400000);
  h.state.testers[0].status='active';h.state.testers[0].token_hash='preserved-active-token';
  const renewed=await actions.reissueInvite({},form({id:h.state.testers[0].id}));
  assert.ok(renewed.code && renewed.code!==created.code);assert.equal(h.state.testers[0].token_hash,'preserved-active-token');
  assert.equal(h.state.revalidations.length,0,'one-time result survives waiting-list promotion');
  h.state.testers[0].status='paused';assert.ok((await actions.reissueInvite({},form({id:h.state.testers[0].id}))).error);
  h.state.owner=false;
  await assert.rejects(()=>actions.createTester({},form({name:'Attacker'})),/owner required/);
  await assert.rejects(()=>actions.reissueInvite({},form({id:'synthetic-0'})),/owner required/);
});

test('pause/revoke actions invalidate pending invitations, revoke also clears bearer',async()=>{
  for(const status of ['paused','revoked']) {
    const h=harness();const {tester}=await seed(h);const original=tester.token_hash;
    await h.load('app/actions').setTesterStatus(form({id:tester.id,status}));
    assert.equal(tester.invite_hash,null);assert.equal(tester.invite_expires_at,null);
    assert.equal(tester.token_hash,status==='revoked'?null:original);
  }
});

test('callback normalizes hostile redirect variants and preserves valid local paths',async()=>{
  const route=harness().load('app/auth/callback/route');
  for(const next of ['/\\evil.example.invalid','//evil.example.invalid','https://evil.example.invalid','javascript:alert(1)','/\n/evil.example.invalid','http://[']) {
    const url=new URL('https://portal.example.invalid/auth/callback?code=synthetic');url.searchParams.set('next',next);
    assert.equal((await route.GET(new Request(url))).headers.get('location'),'https://portal.example.invalid/');
  }
  const url=new URL('https://portal.example.invalid/auth/callback?code=synthetic');url.searchParams.set('next','/testers?active=1');
  assert.equal((await route.GET(new Request(url))).headers.get('location'),'https://portal.example.invalid/testers?active=1');
});
