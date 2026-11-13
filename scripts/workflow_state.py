"""Persistent budget and per-attempt invariants; no credentials belong in these records."""
import copy,time

def history(job):
    if 'attempt_history' not in job:
        job['attempt_history']=[]
        if job.get('reserved_microyuan',0)>0 or job.get('task_id'):
            job['attempt_history'].append({'number':1,'status':job['status'],'task_id':job.get('task_id'),'reserved_microyuan':job.get('reserved_microyuan',0),'migrated':True})
    return job['attempt_history']

def retry_eligible(data,job):
    policy=data.get('unknown_retry_policy',{})
    attempts=job.get('attempt_history')
    count=len(attempts) if attempts is not None else int(job.get('reserved_microyuan',0)>0 or bool(job.get('task_id')))
    return (job['status']=='submission_uncertain' and not job.get('task_id') and policy.get('accept_duplicate_cost') is True and 0<count<1+policy.get('max_extra_attempts',0))

def reserve_attempt(data,job,charge):
    attempts=history(job)
    if job.get('task_id') or job['status'] not in ('pending','submission_uncertain'):raise ValueError('This job cannot be submitted again')
    if job['status']=='submission_uncertain' and not retry_eligible(data,job):raise ValueError('Unknown submission retry is not authorized or limit reached')
    if data['reserved_microyuan']+charge>data['budget_microyuan']:raise ValueError('budget_limit')
    n=len(attempts)+1
    attempts.append({'number':n,'status':'submission_uncertain','reserved_microyuan':charge,'started_at':time.time()})
    data['reserved_microyuan']+=charge;job['reserved_microyuan']=job.get('reserved_microyuan',0)+charge
    job.update(status='submission_uncertain',active_attempt=n)
    return n

def record_id(job,number,task_id):
    attempt=next(x for x in job['attempt_history'] if x['number']==number)
    if attempt.get('task_id') and attempt['task_id']!=task_id:raise ValueError('Attempt already has a different task ID')
    attempt.update(task_id=task_id,status='submitted',submitted_at=time.time())
    if job.get('active_attempt')==number:job.update(task_id=task_id,status='submitted',submitted_at=time.time())
    # A late response is retained in its own attempt, never overwrites the current one.

def budget_context(data,prior_override=None,cap_override=None):
    prior=data.get('prior_potential_charge_microyuan',0)
    if prior_override is not None and 'prior_potential_charge_microyuan' in data and prior_override!=prior and (data.get('jobs') or data.get('budget_microyuan')):raise ValueError('Historical budget occupancy differs from the saved batch')
    if prior_override is not None:prior=prior_override
    cap=data.get('approved_spending_cap_microyuan')
    if cap_override is not None:cap=min(cap,cap_override) if cap is not None else cap_override
    return prior,cap
