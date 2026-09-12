"""Consolidate primary records; submitted snapshots never read mutable sources."""
import hashlib
import json
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.core import DepartmentDailyReport, FinancialDailyImport, InternalOperationRecord, User
from app.models.reporting import OperationalReport, DailyReportEntry, ManagerReportSource, OperationalPending
from app.services.reporting_common import DEPARTMENTS, PERIODS, STATES, METRICS, CATEGORIES, dumps, utc_day, policy, notify_reporting, display_number, display_time, date_ranges, record_day
from app.services.department_presentation import SECTIONS, presentation, reports_pdf, reports_docx
from app.services.cctv import cctv_snapshot, pending_state_at, PENDING_STATES, create_pending
from app.services.report_access import active, view_all

SUPPLEMENTS = {'summary':'Resumo executivo', 'challenges':'Principais desafios', 'recommendations':'Recomendações', 'conclusion':'Conclusão', 'review_notes':'Validação das fontes e divergências'}
SOURCE_TYPES={'daily':'Relatório departamental','entry':'Ocorrência ou indicador','manager':'Documento do Gestor','operation':'Operação interna','pending':'Pendência','cctv':'CCTV'}

def source_details(source):
    data=source['data'];result=[]
    if source['kind']=='daily':
        result=[(title,data.get(field) or 'Não informado') for field,title,_ in SECTIONS[data['department']]]
    else:
        labels={'title':'Título','description':'Descrição','location':'Localização','equipment':'Equipamento','notes':'Observações','owner':'Responsável','due_date':'Prazo','opened_on':'Data de abertura','filename':'Documento original','kind':'Área operacional','asset_name':'Equipamento','quantity':'Quantidade','unit':'Unidade','meter_reading':'Leitura','amount':'Valor','reference_number':'Referência','total':'Câmaras registadas','operational':'Câmaras operacionais','failed':'Câmaras com falha','planned':'Inspeções programadas','executed':'Inspeções concluídas'}
        result=[(label,str(data[key])) for key,label in labels.items() if key in data and data[key] not in (None,'')]
        for metric in data.get('metrics',[]):
            result.append((METRICS[metric['key']][0]+' / '+metric.get('dimension','Geral'),metric['value']+' '+METRICS[metric['key']][1]))
        if data.get('metric_key') and data.get('value') is not None:
            result.append((METRICS[data['metric_key']][0]+' / '+data['dimension'],data['value']+' '+METRICS[data['metric_key']][1]))
    return result

def source(kind, record_id, day, label, data):
    return {'kind':kind, 'id':record_id, 'date':str(day), 'label':label, 'data':data}

def collect_sources(db, department, start, end, daily_id=None, owner_id=None):
    sources=[];points=[];events=[];warnings=[];narratives=defaultdict(list)
    stmt=select(DepartmentDailyReport).where(DepartmentDailyReport.report_date>=utc_day(start),DepartmentDailyReport.report_date<utc_day(end+timedelta(days=1)),DepartmentDailyReport.status.in_(['Submitted','Validated']))
    stmt=stmt.where(active(DepartmentDailyReport,'daily'))
    if owner_id:stmt=stmt.where(DepartmentDailyReport.created_by_id==owner_id)
    if daily_id:stmt=stmt.where(DepartmentDailyReport.id==daily_id)
    elif department!='consolidated':stmt=stmt.where(DepartmentDailyReport.department_key==department)
    daily=db.scalars(stmt.order_by(DepartmentDailyReport.report_date,DepartmentDailyReport.id)).all()
    coverage=defaultdict(set)
    for report in daily:
        day=report.report_date.date().isoformat();coverage[report.department_key].add(day)
        data={field:getattr(report,field) for field,_,_ in SECTIONS[report.department_key]}
        data.update(department=report.department_key,shift=report.shift,prepared_by=report.prepared_by or report.created_by.full_name)
        from app.services.department_tables import present_tables
        data['tables'] = present_tables(report)
        sources.append(source('daily',report.id,day,report.number,data))
        for field,title,_ in SECTIONS[report.department_key]:
            text=(getattr(report,field) or '').strip()
            if text:narratives[(report.department_key,title)].append({'date':day,'text':text,'source_id':report.id})
        for entry in db.scalars(select(DailyReportEntry).where(DailyReportEntry.report_id==report.id).order_by(DailyReportEntry.id)).all():
            detail={'category':entry.category,'title':entry.title,'description':entry.description,'location':entry.location,'equipment':entry.equipment,'department':report.department_key,'requires_action':entry.requires_action,'priority':entry.priority,'occurrence_key':entry.occurrence_key,'metric_key':entry.metric_key,'dimension':entry.dimension,'value':str(entry.value) if entry.value is not None else None}
            sources.append(source('entry',entry.id,day,entry.title,detail))
            events.append({**detail,'date':day,'id':entry.id})
            if entry.metric_key and entry.value is not None:
                points.append({'key':entry.metric_key,'dimension':entry.dimension,'value':str(entry.value),'date':day,'kind':'structured','source':f'entry:{entry.id}'})
    if department=='consolidated':
        imports=db.execute(select(ManagerReportSource,FinancialDailyImport).join(FinancialDailyImport,ManagerReportSource.import_id==FinancialDailyImport.id).where(FinancialDailyImport.report_date>=utc_day(start),FinancialDailyImport.report_date<utc_day(end+timedelta(days=1)))).all()
        imports=[(m,i) for m,i in imports if db.scalar(select(ManagerReportSource.id).where(ManagerReportSource.id==m.id,active(ManagerReportSource,'manager')))]
        superseded={m.supersedes_id for m,_ in imports if m.status=='Reviewed' and m.supersedes_id}
        for manager, imported in imports:
            if not db.scalar(select(ManagerReportSource.id).where(ManagerReportSource.id==manager.id,active(ManagerReportSource,'manager'))):continue
            if manager.id in superseded:continue
            day=imported.report_date.date().isoformat()
            if manager.status!='Reviewed':
                warnings.append(f'Relatório do Gestor de {day} aguarda revisão.');continue
            coverage['consolidated'].add(day)
            data={'filename':imported.original_filename,'fingerprint':manager.fingerprint,'import_id':imported.id,'notes':manager.notes,'metrics':json.loads(manager.metrics),'warning':manager.extraction_warning}
            sources.append(source('manager',manager.id,day,imported.original_filename,data))
            if manager.extraction_warning:warnings.append(f'{day}: {manager.extraction_warning}')
            if manager.notes:narratives[('consolidated','Informação complementar do Gestor')].append({'date':day,'text':manager.notes,'source_id':manager.id})
            for m in data['metrics']:
                points.append({**m,'date':day,'kind':'external','source':f'manager:{manager.id}'})
        operations=db.scalars(select(InternalOperationRecord).where(InternalOperationRecord.record_date>=utc_day(start),InternalOperationRecord.record_date<utc_day(end+timedelta(days=1)),InternalOperationRecord.status.in_(['Registered','Validated'])).order_by(InternalOperationRecord.record_date,InternalOperationRecord.id)).all()
        op_totals=defaultdict(Decimal)
        for record in operations:
            day=record.record_date.date().isoformat()
            detail={k:str(getattr(record,k) or '') for k in ['kind','description','asset_name','quantity','unit','meter_reading','amount','status','reference_number']}
            sources.append(source('operation',record.id,day,record.number,detail))
            dimension=record.asset_name or record.location or 'Geral'
            if record.kind=='fuel' and record.unit.casefold() in {'l','lt','litro','litros'}:
                op_totals[(day,'fuel_litres',dimension)]+=Decimal(str(record.quantity))
            if record.meter_reading is not None and record.kind=='energy':
                points.append({'key':'meter_kwh','dimension':dimension,'value':str(record.meter_reading),'date':day,'kind':'structured','source':f'operation:{record.id}'})
        for (day,key,dimension),value in op_totals.items():points.append({'key':key,'dimension':dimension,'value':str(value),'date':day,'kind':'structured','source':'operation:daily-total'})
    keys=['security','maintenance','it','consolidated'] if department=='consolidated' else [department]
    missing=[]
    day=start
    while day<=end:
        for key in keys:
            if day.isoformat() not in coverage[key]:missing.append({'date':day.isoformat(),'department':key})
        day+=timedelta(days=1)
    return sources,points,events,narratives,missing,warnings

def aggregate_metrics(points):
    daily=defaultdict(list);conflicts=[];selected=[]
    for point in points:daily[(point['date'],point['key'],point.get('dimension',''))].append(point)
    for identity, values in sorted(daily.items()):
        authoritative=[v for v in values if v['kind']=='structured']
        candidates=authoritative or values
        all_values={Decimal(v['value']) for v in values}
        candidate_values={Decimal(v['value']) for v in candidates}
        if len(all_values)>1:
            conflicts.append({'date':identity[0],'key':identity[1],'dimension':identity[2],'values':values,'authoritative':bool(authoritative),'excluded':len(candidate_values)>1})
        # Conflicting authoritative values remain absent until corrected at source.
        if len(candidate_values)==1:selected.append(candidates[0])
    groups=defaultdict(list)
    for point in selected:groups[(point['key'],point.get('dimension',''))].append(point)
    metrics=[]
    for (key,dimension),values in sorted(groups.items()):
        label,unit,mode=METRICS[key];values.sort(key=lambda v:v['date'])
        first,last=Decimal(values[0]['value']),Decimal(values[-1]['value'])
        value=sum((Decimal(v['value']) for v in values),Decimal(0)) if mode=='sum' else last
        delta=last-first if mode=='reading' and len(values)>1 else None
        if delta is not None and delta<0:
            conflicts.append({'date':values[-1]['date'],'key':key,'dimension':dimension,'values':values,'authoritative':True,'excluded':True});delta=None
        metrics.append({'key':key,'label':label,'unit':unit,'dimension':dimension,'mode':mode,'value':str(value),'first':str(first),'delta':str(delta) if delta is not None else None,'days':len(values),'trend':values})
    return metrics,conflicts

def build_snapshot(db,department,start,end,daily_id=None,inspection=False,period=None,owner_id=None):
    sources,points,events,narratives,missing,warnings=collect_sources(db,department,start,end,daily_id,owner_id)
    metrics,conflicts=aggregate_metrics(points)
    grouped_events={}
    for event in events:
        identity=(event['department'],event['occurrence_key'] or f"entry:{event['id']}")
        if identity not in grouped_events:grouped_events[identity]={**event,'references':[]}
        elif ['Normal','Alta','Crítica'].index(event['priority'])>['Normal','Alta','Crítica'].index(grouped_events[identity]['priority']):grouped_events[identity]['priority']=event['priority']
        grouped_events[identity]['references'].append({'date':event['date'],'id':event['id']})
    events=list(grouped_events.values())
    comparison=None
    if period and period!='inspection':
        previous_end=start-timedelta(days=1)
        previous_start=previous_end.replace(day=1) if period=='monthly' else start-timedelta(days=(end-start).days+1)
        previous_sources,previous_points,*_=collect_sources(db,department,previous_start,previous_end,owner_id=owner_id)
        if previous_points:
            previous_metrics,previous_conflicts=aggregate_metrics(previous_points)
            comparison={'date_from':str(previous_start),'date_to':str(previous_end),'metrics':previous_metrics,'conflicts':previous_conflicts,'sources':previous_sources}
    pending=[]
    stmt=select(OperationalPending).where(OperationalPending.opened_on<=end)
    if owner_id:stmt=stmt.where(OperationalPending.owner_id==owner_id)
    if department!='consolidated':stmt=stmt.where(OperationalPending.department_key==department)
    for row in db.scalars(stmt.order_by(OperationalPending.opened_on,OperationalPending.id)).all():
        state=pending_state_at(row,end)
        closures=[h for h in json.loads(row.history or '[]') if h['status']=='Closed' and start<=record_day(h['date'])<=end]
        if state=='Closed' and not closures:continue
        history=json.loads(row.history or '[]')
        at_end=[h for h in history if record_day(h['date'])<=end]
        assignment=(at_end or history[:1] or [{}])[-1]
        assigned_id=assignment.get('owner_id',row.owner_id)
        due_at_end=assignment.get('due_date',str(row.due_date) if row.due_date else None)
        item={'id':row.id,'title':row.title,'department':row.department_key,'opened_on':str(row.opened_on),'status':state,'priority':row.priority,'due_date':str(row.due_date) if row.due_date else None,'origin':row.source_key,'owner':db.get(User,row.owner_id).full_name if row.owner_id else 'Por atribuir','history':[h for h in json.loads(row.history or '[]') if record_day(h['date'])<=end]}
        pending.append(item);sources.append(source('pending',row.id,row.opened_on,row.title,item))
        item['owner']=db.get(User,assigned_id).full_name if assigned_id else 'Por atribuir'
        item['due_date']=due_at_end
    cctv=cctv_snapshot(db,start,end) if department in {'it','consolidated'} and not owner_id else None
    if cctv and cctv['total']:
        sources.append(source('cctv',0,end,'Monitoria e inspeções CCTV',cctv))
    if inspection:missing=[]
    if not sources:raise HTTPException(400,'O período não tem dados para gerar um relatório.')
    return {'schema':1,'generated_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'metrics':metrics,'conflicts':conflicts,'events':events,'narratives':[{'department':k[0],'section':k[1],'items':v} for k,v in narratives.items()],'missing':missing,'warnings':sorted(set(warnings)),'pending':pending,'cctv':cctv,'inspection_only':inspection,'comparison':comparison,'daily_presentation':presentation(db.get(DepartmentDailyReport,daily_id)) if daily_id else None}

def create_report(db,user,department,period,start,end,daily_id=None,new_version=False):
    series=f'{department}:{period}:{start}:{end}'+(f':daily-{daily_id}' if daily_id else '')
    owner_id=None if view_all(user) else user.id
    if owner_id and not daily_id:series+=f':author-{owner_id}'
    previous=db.scalars(select(OperationalReport).where(OperationalReport.series_key==series).order_by(OperationalReport.version.desc())).first()
    previous_active=previous and db.scalar(select(OperationalReport.id).where(OperationalReport.id==previous.id,active(OperationalReport,'operational')))
    if previous_active and not new_version:raise HTTPException(409,f'Já existe o relatório {previous.number}. Consulte o histórico ou crie uma nova versão.')
    if previous_active and previous.status!='Submitted':raise HTTPException(409,'Já existe uma versão em preparação. Continue esse rascunho.')
    snapshot=build_snapshot(db,department,start,end,daily_id,period=='inspection',period,owner_id)
    snapshot['generated_by']=user.full_name
    version=(previous.version+1) if previous else 1
    number=f'REL-{department.upper()}-{period.upper()}-{start}-{hashlib.sha256(series.encode()).hexdigest()[:6]}-V{version}'
    row=OperationalReport(series_key=series,number=number,period=period,department_key=department,date_from=start,date_to=end,version=version,status='Generated',source_daily_id=daily_id,snapshot=dumps(snapshot),created_by_id=user.id,supplements=previous.supplements if previous else '{}')
    db.add(row);db.flush();return row

def add_section(sections,title,lines):
    sections.append({'title':title,'lines':[{'text':str(line),'heading':False} for line in lines] or [{'text':'Não informado.','heading':False}]})

def report_presentation(report,db=None):
    snap=json.loads(report.snapshot);notes=json.loads(report.supplements or '{}');sections=[]
    if snap.get('daily_presentation'):
        item=snap['daily_presentation'];item['number']=report.number;item['id']=report.id
        item['meta'] += [('Versão',str(report.version)),('Submetido por',snap.get('submitted_by','Por submeter'))]
        if snap['events']:add_section(item['sections'],'Ocorrências e indicadores estruturados',[f"{CATEGORIES[e['category']]} · {e['title']} · {e['location']} · {e['equipment']}\n{e['description']}" for e in snap['events']])
        for key,label in SUPPLEMENTS.items():
            if notes.get(key):add_section(item['sections'],label,[notes[key]])
        return item
    completeness='Fontes incompletas' if snap['missing'] else 'Fontes do período disponíveis'
    add_section(sections,'Resumo executivo',[notes.get('summary') or f"{len(snap['sources'])} fontes identificadas; {len(snap['events'])} registos estruturados; {sum(p['status']!='Closed' for p in snap['pending'])} pendências por encerrar.",completeness])
    if snap['missing']:
        groups=defaultdict(list)
        for item in snap['missing']:groups[DEPARTMENTS[item['department']]].append(item['date'])
        add_section(sections,'Disponibilidade das fontes',[f"{key}: faltam {len(days)} dia(s) — {date_ranges(days)}" for key,days in groups.items()])
    if snap['warnings'] or snap['conflicts']:
        lines=snap['warnings']+[f"Informação divergente – requer validação: {METRICS[c['key']][0]} / {c['dimension']} em {c['date']}. Valores: {', '.join(str(v['value'])+' ('+v['source']+')' for v in c['values'])}. "+('Indicador excluído.' if c['excluded'] else 'Mantido o dado estruturado da aplicação.') for c in snap['conflicts']]
        add_section(sections,'Revisão de dados',lines+[notes.get('review_notes','')])
    if snap['metrics']:
        lines=[]
        for m in snap['metrics']:
            text=f"{m['label']} — {m['dimension'] or 'Geral'}: {display_number(m['value'],m['unit'])} {m['unit']} ({m['days']} dia(s) com dados)."
            if m['mode']=='reading':text+=f" Leitura inicial: {display_number(m['first'],m['unit'])}; variação observada: {display_number(m['delta'],m['unit']) if m['delta'] is not None else 'dados insuficientes'}."
            if m['mode']=='last':text+=' Último saldo observado.'
            lines.append(text)
        add_section(sections,'Indicadores operacionais',lines)
    else:
        add_section(sections,'Indicadores operacionais',['Não existem métricas estruturadas validadas neste período.'])
    if snap.get('comparison'):
        previous=snap['comparison']
        lines=[f"Período anterior: {previous['date_from']} a {previous['date_to']}. Comparação dos valores observados; dias sem dados não são considerados zero."]
        previous_by_key={(m['key'],m['dimension']):m for m in previous['metrics']}
        for m in snap['metrics']:
            old=previous_by_key.get((m['key'],m['dimension']))
            if old and m['mode']!='reading':lines.append(f"{m['label']} / {m['dimension']}: {old['value']} → {display_number(m['value'],m['unit'])} {m['unit']}; {old['days']} e {m['days']} dias com dados, respetivamente.")
        add_section(sections,'Comparação com o período anterior',lines)
    for key in ['security','maintenance','it','consolidated']:
        entries=[e for e in snap['events'] if e['department']==key]
        if entries:
            counts=Counter(CATEGORIES[e['category']] for e in entries)
            lines=[f'{label}: {count} registo(s).' for label,count in counts.items()]
            critical=[e for e in entries if e['priority'] in {'Alta','Crítica'}]
            lines += [f"{e['date']} · {e['title']} · {e['location']} — {e['description']}" for e in critical[:12]]
            add_section(sections,DEPARTMENTS[key],lines)
    c=snap.get('cctv')
    if c and c['total']:
        add_section(sections,'CCTV e inspeções',[f"{c['operational']} de {c['total']} câmaras operacionais; {c['failed']} com falha; {c['total']-c['known']} sem observação.",f"Disponibilidade: {str(c['availability'])+'%' if c['availability'] is not None else 'dados insuficientes'}. Sem gravação: {c['without_recording']}; necessitam limpeza: {c['needs_cleaning']}.",f"Novas falhas: {c['new_failures']}; falhas resolvidas: {c['resolved_failures']}; tempo médio de avaria resolvida: {str(c['mean_failure_hours'])+' horas' if c['mean_failure_hours'] is not None else 'dados insuficientes'}.",f"Inspeções programadas: {c['planned']}; concluídas: {c['executed']}; não executadas: {c['not_executed']}; cumprimento: {str(c['compliance'])+'%' if c['compliance'] is not None else 'sem programação' }."])
    if snap['pending']:
        add_section(sections,'Acompanhamento de pendências',[f"{'Anterior' if p['opened_on']<str(report.date_from) else 'Aberta no período'} · {p['title']} · {PENDING_STATES[p['status']]} · {p['priority']} · {p['owner']} · prazo {p['due_date'] or 'não definido'}" for p in snap['pending']])
    for key in ['challenges','recommendations','conclusion']:add_section(sections,SUPPLEMENTS[key],[notes[key]] if notes.get(key) else [])
    # Narratives are grouped by subject, retaining dates and source IDs, outside the executive summary.
    for src in snap['sources']:
        if src['kind'] == 'daily' and src['data'].get('tables'):
            sections.append({'title': 'Anexo — ' + DEPARTMENTS[src['data']['department']] + ' / ' + src['date'] + ' / ' + src['label'], 'lines': [], 'tables': src['data']['tables']})
    for group in snap['narratives']:
        grouped=defaultdict(list)
        for entry in group['items']:grouped[entry['text']].append(f"{entry['date']} / #{entry['source_id']}")
        add_section(sections,'Anexo — '+DEPARTMENTS[group['department']]+' / '+group['section'],[f"{', '.join(refs)}\n{text}" for text,refs in grouped.items()])
    if snap['events']:add_section(sections,'Anexo — registos estruturados',[f"#{e['id']} · {e['date']} · {CATEGORIES[e['category']]} · {e['title']} · {e['location']} · {e['equipment']}\n{e['description']}" for e in snap['events']])
    if c and c['total']:
        add_section(sections,'Anexo — detalhe CCTV',[f"{d['code']} / {d['area']}: {d['status']}; {d['days_operational']} dias operacionais, {d['days_recording']} dias com gravação, {d['known_days']} dias observados. {d['notes']}" for d in c['cameras']])
        if c['inspections']:add_section(sections,'Anexo — inspeções CCTV',[f"{i['scheduled_on']} · {i['code']} · {i['result']} · {i['notes']}" for i in c['inspections']])
    add_section(sections,'Fontes e rastreabilidade',[f"{SOURCE_TYPES[s['kind']]} #{s['id']} · {s['date']} · {s['label']}" for s in snap['sources']])
    if snap.get('comparison'):add_section(sections,'Fontes do comparativo anterior',[f"{SOURCE_TYPES[s['kind']]} #{s['id']} · {s['date']} · {s['label']}" for s in snap['comparison']['sources']])
    charts=[{**m,'maximum':max(float(p['value']) for p in m['trend']) or 1} for m in snap['metrics'] if len(m['trend'])>1]
    return {'id':report.id,'number':report.number,'title':f"Relatório {PERIODS[report.period].lower()} — {DEPARTMENTS[report.department_key]}",'meta':[('Período',f'{report.date_from:%d/%m/%Y} a {report.date_to:%d/%m/%Y}'),('Versão',str(report.version)),('Estado',STATES[report.status]),('Gerado por',snap.get('generated_by','Não informado')),('Gerado em',display_time(snap['generated_at'])),('Submetido por',snap.get('submitted_by','Por submeter')),('Submetido em',display_time(report.submitted_at))],'sections':sections,'charts':charts}

def submit_report(db,row,user):
    if row.status=='Submitted':raise HTTPException(409,'O relatório já foi submetido. Crie uma nova versão para corrigir.')
    snap=json.loads(row.snapshot);notes=json.loads(row.supplements or '{}')
    if snap['missing'] and (not policy(db).allow_partial or not notes.get('review_notes','').strip()):
        raise HTTPException(409,'Existem fontes em falta. A submissão parcial requer autorização nas configurações e justificação da revisão.')
    if snap['conflicts'] or snap['warnings']:
        if not notes.get('review_notes','').strip():raise HTTPException(409,'Registe a validação das fontes e divergências antes de submeter.')
        if any(c['excluded'] for c in snap['conflicts']):raise HTTPException(409,'Corrija os valores contraditórios na origem e regenere o rascunho antes de submeter.')
    row.submitted_at=datetime.now(timezone.utc);row.submitted_by_id=user.id;row.status='Submitted'
    snap['submitted_by']=user.full_name;row.snapshot=dumps(snap)
    item=report_presentation(row)
    try:
        row.pdf=reports_pdf([item],item['title'],user.full_name)
        row.docx=reports_docx([item],item['title'],user.full_name)
    except Exception as exc:raise HTTPException(500,'Não foi possível gerar os documentos. O rascunho foi preservado; tente novamente.') from exc
    title='Relatório mensal disponível' if row.period=='monthly' else ('Relatório consolidado submetido' if row.department_key=='consolidated' else 'Relatório departamental submetido')
    notify_reporting(db,user,title,row.number,row.id,row.department_key!='consolidated')

def archive_daily(db,report,user):
    for entry in db.scalars(select(DailyReportEntry).where(DailyReportEntry.report_id==report.id,DailyReportEntry.requires_action==True)).all():
        key=f'occurrence:{report.department_key}:{entry.occurrence_key}' if entry.occurrence_key else f'entry:{entry.id}'
        create_pending(db,user,key,report.department_key,entry.title,entry.description,owner=entry.owner_id,priority=entry.priority,due=entry.due_date,opened=report.report_date.date())
    row=create_report(db,user,report.department_key,'daily',report.report_date.date(),report.report_date.date(),daily_id=report.id)
    submit_report(db,row,user)
    return row
