"""Validated, persisted workflow graphs for the supported VideoStudio pipeline.

Connections describe data dependencies, not arbitrary code execution. The fixed
worker stage order is a valid topological ordering of every accepted graph.
"""
from __future__ import annotations
import copy
import json
import math
import re
import time
import uuid

OPTIONAL = {'research', 'references', 'captions', 'music', 'sfx'}
REQUIRED = {'input', 'script', 'speech', 'images', 'render', 'output'}
# Input and output sockets carry domain types; the same type cannot impersonate a
# different stage. Required socket sets are independently checked below.
PORTS = {
    'input': ({}, {'brief':'brief'}),
    'research': ({'brief':'brief'}, {'brief':'brief'}),
    'script': ({'brief':'brief'}, {'script':'script'}),
    'speech': ({'script':'script'}, {'speech':'speech'}),
    'references': ({'script':'script'}, {'references':'references'}),
    'images': ({'script':'script','speech':'speech','references':'references'}, {'images':'images'}),
    'captions': ({'speech':'speech'}, {'captions':'captions'}),
    'music': ({'speech':'speech'}, {'music':'music'}),
    'sfx': ({'speech':'speech'}, {'sfx':'sfx'}),
    'render': ({'images':'images','speech':'speech','captions':'captions','music':'music','sfx':'sfx'}, {'video':'video'}),
    'output': ({'video':'video'}, {}),
}
REQUIRED_PORTS = {key: set(value[0]) for key,value in PORTS.items()}
REQUIRED_PORTS['images'] = {'script','speech'}
REQUIRED_PORTS['render'] = {'images','speech'}
CONFIG = {
    'input': {'idea','duration_seconds','workflow_mode'},
    'research': {'enabled','provider'}, 'script': {'provider'},
    'speech': {'voice_id','pitch'}, 'references': {'enabled'},
    'images': {'provider','batch_size','quality_mode'}, 'captions': {'enabled'},
    'music': {'enabled','volume'}, 'sfx': {'enabled'},
    'render': {'preset_id'}, 'output': set(),
}
RANK = {'input':0,'research':1,'script':2,'speech':3,'references':3,'images':4,'captions':4,'music':4,'sfx':4,'render':5,'output':6}

def _finite(value, low, high, name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Invalid {name}: expected finite number {low}–{high}')
    return value

def _identifier(value, name, empty=False):
    if not isinstance(value,str) or (not value and not empty) or len(value)>100 or (value and not re.fullmatch(r'[A-Za-z0-9_-]+',value)):
        raise ValueError(f'Invalid {name}')
    return value

def _config(kind, config):
    if not isinstance(config,dict) or set(config)-CONFIG[kind]: raise ValueError(f'Unsupported {kind} config')
    result=copy.deepcopy(config)
    for key,value in config.items():
        if key=='enabled' and type(value) is not bool: raise ValueError('enabled must be boolean')
        if key=='provider' and value not in (('flow','chatgpt','comfy','meta') if kind=='images' else ('chatgpt','gemini')): raise ValueError(f'Unsupported {kind} provider')
        if key=='batch_size' and (type(value) is not int or value not in (1,3,5,10)): raise ValueError('Invalid batch_size')
        if key=='quality_mode' and value not in ('quick','careful'): raise ValueError('Invalid quality_mode')
        if key=='workflow_mode' and value not in ('research','provided_narration'): raise ValueError('Invalid workflow_mode')
        if key=='preset_id' and value not in ('documentary','science','everyday'): raise ValueError('Invalid preset_id')
        if key in ('idea','voice_id') and (not isinstance(value,str) or not value.strip() or len(value)>(100000 if key=='idea' else 200)): raise ValueError(f'Invalid {key}')
        if key=='duration_seconds': _finite(value,8,7200,key)
        if key=='pitch': _finite(value,-12,12,key)
        if key=='volume': _finite(value,0,1,key)
    if kind=='images' and config.get('provider','flow')!='flow' and config.get('batch_size',1)!=1:
        raise ValueError('batch_size above 1 requires Google Flow')
    return result

def validate_workflow(graph):
    if not isinstance(graph,dict) or type(graph.get('schema_version')) is not int or graph.get('schema_version')!=1: raise ValueError('workflow schema_version must be 1')
    if set(graph)-{'schema_version','id','name','revision','nodes','edges','viewport'}: raise ValueError('Unknown workflow fields')
    result={'schema_version':1,'id':_identifier(graph.get('id',''),'workflow id',True),'name':graph.get('name','Untitled workflow'),'revision':graph.get('revision',0)}
    if not isinstance(result['name'],str) or not 1<=len(result['name'].strip())<=200: raise ValueError('Invalid workflow name')
    result['name']=result['name'].strip()
    if type(result['revision']) is not int or result['revision']<0: raise ValueError('Invalid workflow revision')
    raw_nodes=graph.get('nodes');raw_edges=graph.get('edges')
    if not isinstance(raw_nodes,list) or not 1<=len(raw_nodes)<=32 or not isinstance(raw_edges,list) or len(raw_edges)>40: raise ValueError('Invalid workflow nodes/edges')
    nodes={};kinds={};result['nodes']=[]
    for node in raw_nodes:
        if not isinstance(node,dict) or set(node)-{'id','type','x','y','config'}: raise ValueError('Invalid node')
        ident=_identifier(node.get('id'),'node id');kind=node.get('type')
        if not isinstance(kind,str):raise ValueError('Unsupported node type')
        if ident in nodes or kind in kinds: raise ValueError('Duplicate node id or type')
        if kind not in PORTS: raise ValueError('Unsupported node type')
        norm={'id':ident,'type':kind,'x':_finite(node.get('x',0),-100000,100000,'node x'),'y':_finite(node.get('y',0),-100000,100000,'node y'),'config':_config(kind,node.get('config',{}))}
        nodes[ident]=norm;kinds[kind]=norm;result['nodes'].append(norm)
    if REQUIRED-set(kinds): raise ValueError('Missing required nodes: '+', '.join(sorted(REQUIRED-set(kinds))))
    incoming={ident:{} for ident in nodes};adj={ident:[] for ident in nodes};edge_ids=set();result['edges']=[]
    for edge in raw_edges:
        if not isinstance(edge,dict) or set(edge)!={'id','source','source_port','target','target_port'}: raise ValueError('Invalid edge')
        ident=_identifier(edge['id'],'edge id');source=_identifier(edge['source'],'edge source');target=_identifier(edge['target'],'edge target')
        _identifier(edge['source_port'],'source port');_identifier(edge['target_port'],'target port')
        if ident in edge_ids: raise ValueError('Duplicate edge id')
        edge_ids.add(ident)
        if source not in nodes or target not in nodes: raise ValueError('Unknown edge node')
        source_ports=PORTS[nodes[source]['type']][1];target_ports=PORTS[nodes[target]['type']][0]
        if edge['source_port'] not in source_ports or edge['target_port'] not in target_ports or source_ports[edge['source_port']]!=target_ports[edge['target_port']]: raise ValueError('Incompatible or unknown port')
        if edge['target_port'] in incoming[target]: raise ValueError('Input port already connected')
        incoming[target][edge['target_port']]=source;adj[source].append(target);result['edges'].append(dict(edge))
    visiting=set();visited=set();order=[]
    def visit(ident):
        if ident in visiting: raise ValueError('Workflow cycle detected')
        if ident in visited:return
        visiting.add(ident)
        for child in adj[ident]:visit(child)
        visiting.remove(ident);visited.add(ident);order.append(ident)
    for ident in nodes:visit(ident)
    for node in nodes.values():
        missing=REQUIRED_PORTS[node['type']]-set(incoming[node['id']])
        if missing: raise ValueError(f"{node['type']} missing required input: {', '.join(sorted(missing))}")
    for edge in result['edges']:
        source_kind=nodes[edge['source']]['type'];target_kind=nodes[edge['target']]['type']
        if RANK[source_kind]>=RANK[target_kind]:raise ValueError('Unsupported execution dependency order')
    # Every node must contribute to output, even disabled passthrough nodes.
    contributors=set()
    def collect(ident):
        if ident in contributors:return
        contributors.add(ident)
        for source in incoming[ident].values():collect(source)
    collect(kinds['output']['id'])
    if set(nodes)-contributors:raise ValueError('Every node must be connected to output')
    viewport=graph.get('viewport',{'x':20,'y':30,'zoom':0.7})
    if not isinstance(viewport,dict) or set(viewport)-{'x','y','zoom'}:raise ValueError('Invalid viewport')
    result['viewport']={'x':_finite(viewport.get('x',0),-100000,100000,'viewport x'),'y':_finite(viewport.get('y',0),-100000,100000,'viewport y'),'zoom':_finite(viewport.get('zoom',1),0.15,2,'viewport zoom')}
    return result

def execution_order(graph):
    graph=validate_workflow(graph)
    return [n['id'] for n in sorted(graph['nodes'],key=lambda n:RANK[n['type']])]

def default_workflow(preset_id='documentary'):
    if preset_id not in ('documentary','science','everyday'):raise ValueError('Invalid preset_id')
    layout={'input':(30,100),'research':(290,100),'script':(550,100),'speech':(810,100),'references':(810,340),'images':(1080,100),'captions':(1080,340),'music':(1080,560),'sfx':(1080,780),'render':(1370,100),'output':(1640,100)}
    configs={'research':{'enabled':True},'script':{},'images':{'provider':'flow','batch_size':1},'music':{'enabled':True,'volume':0.15},'render':{'preset_id':preset_id}}
    graph={'schema_version':1,'id':'','name':preset_id.title()+' workflow','revision':0,'nodes':[{'id':kind,'type':kind,'x':xy[0],'y':xy[1],'config':configs.get(kind,{})} for kind,xy in layout.items()],'edges':[],'viewport':{'x':20,'y':30,'zoom':0.55}}
    def edge(source,port,target,target_port=None):graph['edges'].append({'id':f'{source}-{target}-{port}','source':source,'source_port':port,'target':target,'target_port':target_port or port})
    edge('input','brief','research');edge('research','brief','script');edge('script','script','speech');edge('script','script','references');edge('script','script','images');edge('speech','speech','images');edge('references','references','images');edge('images','images','render');edge('speech','speech','render')
    for kind in ('captions','music','sfx'):edge('speech','speech',kind);edge(kind,kind,'render')
    edge('render','video','output')
    return graph

def compile_workflow(graph,base_request):
    graph=validate_workflow(graph)
    if not isinstance(base_request,dict):raise ValueError('request must be an object')
    result=copy.deepcopy(base_request);nodes={n['type']:n['config'] for n in graph['nodes']}
    def enabled(kind):return kind in nodes and nodes[kind].get('enabled',True)
    result.update(nodes['input'])
    mode=result.get('workflow_mode')
    result['workflow_mode']='provided_narration' if mode=='provided_narration' or not enabled('research') else 'research'
    providers=[nodes[kind]['provider'] for kind in ('research','script') if kind in nodes and (kind!='research' or enabled('research')) and 'provider' in nodes[kind]]
    if len(set(providers))>1:raise ValueError('Research and script must use the same text provider')
    result['text_provider']=providers[0] if providers else result.get('text_provider','chatgpt')
    images=nodes['images'];result['image_provider']=images.get('provider',result.get('image_provider','flow'))
    result['flow_batch_size']=images.get('batch_size',result.get('flow_batch_size',1) if result['image_provider']=='flow' else 1)
    if 'quality_mode' in images:result['quality_mode']=images['quality_mode']
    result.update(nodes['speech'])
    for kind in ('references','captions','music','sfx'):result[kind+'_enabled']=enabled(kind)
    if result['references_enabled'] and result['image_provider']!='flow':raise ValueError('Native character references require Google Flow; disable the reference node for another image provider')
    if 'music' in nodes and 'volume' in nodes['music']:result['music_volume']=nodes['music']['volume']
    result['edit_preset']=nodes['render'].get('preset_id',result.get('edit_preset','documentary'))
    result['workflow']=graph
    return result

class WorkflowService:
    def __init__(self,store):
        self.store=store
        with store.db() as c:c.executescript('CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY,graph TEXT NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL); CREATE TABLE IF NOT EXISTS workflow_revisions(id TEXT NOT NULL,revision INTEGER NOT NULL,graph TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(id,revision));')
    def list(self):
        with self.store.db() as c:rows=c.execute('SELECT graph FROM workflows ORDER BY updated DESC').fetchall()
        return {'items':[json.loads(r['graph']) for r in rows],'templates':[default_workflow(p) for p in ('documentary','science','everyday')],'node_types':{kind:{'inputs':inputs,'outputs':outputs,'required_inputs':sorted(REQUIRED_PORTS[kind]),'optional':kind in OPTIONAL} for kind,(inputs,outputs) in PORTS.items()}}
    def get(self,ident):
        with self.store.db() as c:row=c.execute('SELECT graph FROM workflows WHERE id=?',(ident,)).fetchone()
        if not row:raise KeyError(ident)
        return json.loads(row['graph'])
    def save(self,graph,revision):
        graph=validate_workflow(graph)
        if type(revision) is not int or revision<0:raise ValueError('Invalid revision')
        ident=graph['id'] or str(uuid.uuid4());now=time.time()
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT revision FROM workflows WHERE id=?',(ident,)).fetchone()
            current=row['revision'] if row else 0
            if revision!=current:raise ValueError('Stale workflow revision; reload before saving')
            graph.update(id=ident,revision=current+1);payload=json.dumps(graph,ensure_ascii=False)
            c.execute('INSERT INTO workflows VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET graph=excluded.graph,revision=excluded.revision,updated=excluded.updated',(ident,payload,current+1,now))
            c.execute('INSERT INTO workflow_revisions VALUES(?,?,?,?)',(ident,current+1,payload,now))
        return graph
    def revisions(self,ident):
        self.get(ident)
        with self.store.db() as c:return [json.loads(r['graph']) for r in c.execute('SELECT graph FROM workflow_revisions WHERE id=? ORDER BY revision DESC',(ident,)).fetchall()]
    def delete(self,ident):
        with self.store.db() as c:
            if not c.execute('DELETE FROM workflows WHERE id=?',(ident,)).rowcount:raise KeyError(ident)
            c.execute('DELETE FROM workflow_revisions WHERE id=?',(ident,))
        return {'deleted':ident}
