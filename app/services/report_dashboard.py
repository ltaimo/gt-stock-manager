"""Automatic report visuals, derived only from the saved consolidation snapshot."""
import base64
from collections import Counter
from datetime import date
from io import BytesIO
from pathlib import Path
from functools import lru_cache
import reportlab
from PIL import Image, ImageDraw, ImageFont
from app.services.reporting_common import CATEGORIES, display_number

INK='#263238'; GOLD='#D6A619'; TEAL='#247F87'; GREY='#89949F'; LIGHT='#F4F6F8'; RED='#BA4E48'

def dashboard_data(report,snapshot):
    days=(report.date_to-report.date_from).days+1
    expected=days*(4 if report.department_key=='consolidated' else 1)
    missing=len(snapshot.get('missing',[]))
    cards=[('Fontes identificadas',str(len(snapshot.get('sources',[])))),
           ('Cobertura dos diários',f'{max(0,expected-missing)}/{expected}'),
           ('Registos estruturados',str(len(snapshot.get('events',[])))),
           ('Pendências abertas',str(sum(p['status']!='Closed' for p in snapshot.get('pending',[]))))]
    charts=[]
    def bars(title,unit,rows,labels=('Valor observado',),note=''):
        for offset in range(0,len(rows),8):
            charts.append({'kind':'bars','title':title+(f' · {offset//8+1}' if len(rows)>8 else ''),'unit':unit,'rows':rows[offset:offset+8],'labels':list(labels),'note':note})
    metrics=snapshot.get('metrics',[])
    old={(m['key'],m['dimension']):m for m in (snapshot.get('comparison') or {}).get('metrics',[])}
    by_key={}
    for metric in metrics:by_key.setdefault(metric['key'],[]).append(metric)
    for key,items in by_key.items():
        first=items[0];mode=first['mode']
        explanation={'sum':'Total dos dias com observação.','last':'Último saldo observado por dimensão; não é a soma dos saldos diários.','reading':'Última leitura observada; não equivale a consumo.'}[mode]
        rows=[{'label':m['dimension'] or 'Geral','values':[float(m['value'])],'detail':f"{m['days']} dia(s) com dados"} for m in items]
        bars(first['label']+' por dimensão',first['unit'],rows,note=explanation)
        comparable=[m for m in items if (key,m['dimension']) in old and mode!='reading']
        if comparable:
            previous=snapshot['comparison']
            bars(first['label']+' · comparação',first['unit'],[{'label':m['dimension'] or 'Geral','values':[float(old[key,m['dimension']]['value']),float(m['value'])],'detail':f"{old[key,m['dimension']]['days']} / {m['days']} dias com dados"} for m in comparable],('Anterior','Atual'),f"Anterior: {previous['date_from']} a {previous['date_to']}. Compare também a cobertura dos períodos.")
        for m in items:
            if len(m['trend'])>1:charts.append({'kind':'trend','title':m['label']+' · '+(m['dimension'] or 'Geral'),'unit':m['unit'],'trend':m['trend'],'note':'Evolução das observações. Intervalos sem dados ficam sem ligação.'})
    counts=Counter(CATEGORIES.get(e['category'],e['category']) for e in snapshot.get('events',[]))
    if counts:bars('Ocorrências e indicadores registados','registos',[{'label':k,'values':[v]} for k,v in counts.items()],note='Contagem dos registos estruturados; não interpreta automaticamente o texto livre.')
    tables=Counter()
    for source in snapshot.get('sources',[]):
        if source['kind']=='daily':
            for table in source['data'].get('tables',[]):tables[table['title']]+=len(table.get('rows',[]))
    if tables:bars('Atividade registada nas tabelas','linhas',[{'label':k,'values':[v]} for k,v in tables.items()],note='Linhas preenchidas nos relatórios de origem. Não representam pessoas, viaturas ou equipamentos únicos.')
    pending=Counter(p['status'] for p in snapshot.get('pending',[]))
    if pending:
        from app.services.cctv import PENDING_STATES
        bars('Acompanhamento das pendências','pendências',[{'label':PENDING_STATES.get(k,k),'values':[v]} for k,v in pending.items()])
    c=snapshot.get('cctv')
    if c and c['total']:
        bars('CCTV · estado das câmaras','câmaras',[{'label':'Operacionais','values':[c['operational']]},{'label':'Com falha','values':[c['failed']]},{'label':'Sem observação','values':[c['total']-c['known']]}],note='Último estado observado até ao fim do período. Sem observação não significa avaria.')
        bars('CCTV · inspeção e limpeza','inspeções',[{'label':'Programadas','values':[c['planned']]},{'label':'Concluídas','values':[c['executed']]},{'label':'Sem conclusão registada','values':[c['not_executed']]}],note='Inclui tarefas previstas no intervalo; tarefas futuras ainda não têm execução.')
    return {'period':f'{report.date_from:%d/%m/%Y} a {report.date_to:%d/%m/%Y}','cards':cards,'charts':charts,'missing':missing,'conflicts':len(snapshot.get('conflicts',[])),'has_metrics':bool(metrics)}

@lru_cache(maxsize=24)
def font(size):
    return ImageFont.truetype(str(Path(reportlab.__file__).parent/'fonts'/'Vera.ttf'),size)

def wrapped(draw,text,xy,width,size=24,fill=INK):
    x,y=xy;line='';f=font(size)
    for word in str(text).split():
        candidate=(line+' '+word).strip()
        if draw.textlength(candidate,font=f)>width and line:
            draw.text((x,y),line,font=f,fill=fill);y+=size+7;line=word
        else:line=candidate
    draw.text((x,y),line,font=f,fill=fill)
    return y+size+7

def canvas(title,subtitle,height):
    image=Image.new('RGB',(1200,height),'white');draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((0,0,1199,height-1),radius=20,outline='#D9DFE4',width=2)
    heading=str(title);heading_font=font(30)
    while draw.textlength(heading,font=heading_font)>1115:heading=heading[:-2].rstrip('…')+'…'
    draw.text((42,28),heading,font=heading_font,fill=INK)
    draw.text((42,83),subtitle,font=font(22),fill='#586872')
    draw.line((42,122,1158,122),fill=GOLD,width=5)
    return image,draw

def overview(data):
    image,draw=canvas('Dashboard do relatório',data['period'],530)
    for i,(label,value) in enumerate(data['cards']):
        x=42+i*283
        draw.rounded_rectangle((x,155,x+265,310),radius=15,fill=LIGHT)
        draw.rectangle((x+18,176,x+24,285),fill=GOLD)
        draw.text((x+40,181),value,font=font(43),fill=INK)
        wrapped(draw,label,(x+40,245),210,21)
    draw.text((42,344),'LEITURA DO PERÍODO',font=font(23),fill=TEAL)
    note=f"{data['missing']} dia(s)/departamento sem diário; {data['conflicts']} divergência(s) de dados para revisão."
    y=wrapped(draw,note,(42,387),1100,25)
    wrapped(draw,'Os gráficos usam os dados guardados nesta versão.' if data['has_metrics'] else 'Sem indicadores numéricos validados. Os gráficos disponíveis mostram apenas registos e atividade confirmada.',(42,y+10),1100,22)
    return image

def chart_image(chart):
    if chart['kind']=='trend':return trend_image(chart)
    height=235+len(chart['rows'])*92
    image,draw=canvas(chart['title'],chart['unit'],height)
    series=len(chart['labels']);colors=[GOLD,TEAL]
    for i,label in enumerate(chart['labels']):
        x=440+i*260;draw.rectangle((x,143,x+18,161),fill=colors[i%2]);draw.text((x+28,139),label,font=font(21),fill=INK)
    values=[v for row in chart['rows'] for v in row['values']]
    low=min([0]+values);high=max([0]+values);span=high-low or 1
    origin=445+(0-low)/span*495
    for i,row in enumerate(chart['rows']):
        y=184+i*92
        label=row['label'] if len(row['label'])<=52 else row['label'][:49]+'…'
        wrapped(draw,label,(42,y),370,23)
        if row.get('detail'):draw.text((42,y+55),row['detail'],font=font(17),fill='#65737D')
        for j,value in enumerate(row['values']):
            yy=y+j*29;end=445+(value-low)/span*495
            draw.line((origin,yy,origin,yy+22),fill=GREY,width=2)
            if value:draw.rectangle((min(origin,end),yy,max(origin,end),yy+22),fill=colors[j%2])
            draw.text((965,yy-4),display_number(round(value,2)),font=font(22),fill=INK)
    wrapped(draw,chart.get('note','') or 'Valores observados no período selecionado.',(42,height-48),1110,18)
    return image

def trend_image(chart):
    points=chart['trend'];image,draw=canvas(chart['title'],chart['unit'],570)
    left,right,top,bottom=130,1125,165,430
    values=[float(p['value']) for p in points];low=min([0]+values);high=max([0]+values);span=high-low or 1
    first=date.fromisoformat(points[0]['date']);last=date.fromisoformat(points[-1]['date']);days=max(1,(last-first).days)
    for i in range(5):
        value=low+span*i/4;y=bottom-(bottom-top)*i/4
        draw.line((left,y,right,y),fill='#E3E8EB');draw.text((12,y-13),display_number(round(value,1)),font=font(20),fill=GREY)
    previous=None
    for i,point in enumerate(points):
        day=date.fromisoformat(point['date']);x=left+(right-left)*(day-first).days/days;y=bottom-(bottom-top)*(float(point['value'])-low)/span
        if previous and (day-previous[2]).days==1:draw.line((previous[0],previous[1],x,y),fill=GOLD,width=5)
        draw.ellipse((x-5,y-5,x+5,y+5),fill=TEAL)
        if i%max(1,(len(points)+5)//6)==0 or i==len(points)-1:draw.text((x-32,450),day.strftime('%d/%m'),font=font(20),fill=INK)
        previous=x,y,day
    wrapped(draw,chart['note'],(42,510),1100,21)
    return image

def dashboard_images(data):
    images=[('Dashboard do relatório',overview(data),'Resumo das fontes, cobertura, registos e pendências.')]
    images += [(c['title'],chart_image(c),c.get('note','')) for c in data['charts']]
    output=[]
    for title,image,note in images:
        out=BytesIO();image.save(out,format='PNG')
        output.append({'title':title,'note':note,'height':image.height,'width':image.width,'data':base64.b64encode(out.getvalue()).decode()})
    return output
