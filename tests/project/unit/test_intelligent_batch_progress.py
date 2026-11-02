"""Live original-job status in manual and automatic episode batch views."""
import subprocess
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]


class IntelligentBatchProgressTests(unittest.TestCase):
    def check(self,body):
        code="const assert=require('node:assert/strict');const {loadModule}=require('./tests/support/fixtures/frontend/modules.cjs');(async()=>{const {readIntelligentBatchProgress:read}=await loadModule('intelligent-production.js');"+body+"})().catch(e=>{console.error(e);process.exit(1)});"
        result=subprocess.run(['node','-e',code],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_manual_completion_refreshes_original_jobs_then_stops(self):
        self.check("const calls=[];const api=async path=>{calls.push(path);return path.endsWith('/b')?{status:'manual',jobs:[]}:{batches:[{id:'b',jobs:[{id:'j',status:'succeeded'}]}]};};const r=await read(api,'/p','w','b',[{id:'j',status:'created'}]);assert.equal(r.value.status,'manual');assert.equal(r.jobs[0].status,'succeeded');assert.equal(r.keepPolling,false);assert.deepEqual(calls,['/p/intelligent-work-batches/b','/p/intelligent-workflows/w']);calls.length=0;await read(api,'/p','w','b',r.jobs);assert.equal(calls.length,1);")

    def test_manual_and_preserved_edits_keep_polling_running_jobs(self):
        self.check("for(const status of ['manual','edit_changed']){const api=async path=>path.endsWith('/b')?{status,jobs:[]}:{batches:[{id:'unrelated',jobs:[{status:'succeeded'}]},{id:'b',jobs:[{id:'j',status:'running'}]}]};const r=await read(api,'/p','w','b',[{id:'j',status:'created'}]);assert.equal(r.jobs[0].status,'running');assert.equal(r.keepPolling,true);}")

    def test_successful_first_cut_tracks_alternative_until_its_original_job_finishes(self):
        self.check("const api=async path=>path.endsWith('/b')?{status:'succeeded',jobs:[{id:'j',status:'running'}]}:{batches:[{id:'b',jobs:[{id:'j',status:'failed'}]}]};const r=await read(api,'/p','w','b',[{id:'j',status:'running'}]);assert.equal(r.jobs[0].status,'failed');assert.equal(r.keepPolling,false);const queued=await read(async()=>({status:'queued',jobs:[{id:'j',status:'succeeded'}]}),'/p','w','b',[{id:'j',status:'succeeded'}]);assert.equal(queued.keepPolling,true);")

    def test_waiting_batch_uses_live_status_without_extra_workflow_read_or_writes(self):
        self.check("const calls=[];const api=async(...args)=>{assert.equal(args.length,1);calls.push(args[0]);return {status:'waiting',jobs:[{id:'j',status:'running'}]};};const r=await read(api,'/p','w','b',[{id:'j',status:'created'}]);assert.equal(r.jobs[0].status,'running');assert.equal(r.keepPolling,true);assert.equal(calls.length,1);await assert.rejects(()=>read(async()=>{throw new Error('offline')},'/p','w','b',[]),/offline/);")
