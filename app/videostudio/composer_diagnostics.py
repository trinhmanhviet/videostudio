"""Bounded local composer evidence, never a prompt or a success receipt."""
def bounded_diagnostic(value):
    if not isinstance(value,dict):raise ValueError('Composer diagnostic object required')
    result={}
    for key in ('expected_length','actual_length','first_diff','rendered_length','textcontent_length'):
        number=value.get(key)
        if type(number) is int and 0<=number<=10_000_000:result[key]=number
    for key in ('expected_context','actual_context','editor_html_excerpt'):
        if isinstance(value.get(key),str):result[key]=value[key][:1200 if key=='editor_html_excerpt' else 512]
    for key in ('expected_codepoints','actual_codepoints'):
        points=value.get(key)
        if isinstance(points,list):result[key]=[str(point)[:32] for point in points[:40]]
    nodes=value.get('inline_nodes')
    if isinstance(nodes,list):
        result['inline_nodes']=[]
        for node in nodes[:10]:
            if not isinstance(node,dict):continue
            result['inline_nodes'].append({key:node[key][:400] for key in ('tag','contenteditable','aria_hidden','class_name','text_excerpt','html_excerpt') if isinstance(node.get(key),str)})
    return result
