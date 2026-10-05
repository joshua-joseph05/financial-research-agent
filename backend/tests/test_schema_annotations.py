from copy import deepcopy
from app.providers.schema_annotations import without_titles, trim_tool_schema_titles


def test_titles_removed_without_changing_properties_defaults_or_descriptions():
    schema={'title':'Answer','type':'object','required':['title'],
            'properties':{'title':{'title':'Title','type':'string','description':'Source title',
                                   'default':'A title'},
                          'metadata':{'type':'object','default':{'title':'Retain me'}}},
            '$defs':{'title':{'title':'Definition','enum':[{'title':'Value'}]}},
            'anyOf':[{'title':'Branch','properties':{'x':{'title':'X','const':0}}}],
            'additionalProperties':False}
    original=deepcopy(schema)
    result=without_titles(schema)
    assert schema==original
    assert 'title' not in result
    assert result['required']==['title']
    assert result['properties']['title']=={'type':'string','description':'Source title','default':'A title'}
    assert result['properties']['metadata']['default']=={'title':'Retain me'}
    assert result['$defs']['title']['enum']==[{'title':'Value'}]
    assert result['anyOf'][0]['properties']['x']=={'const':0}
    assert result['additionalProperties'] is False


def test_tool_trimming_preserves_source_text_and_tool_descriptions():
    context={'available_tools':[{'name':'read','description':'Read cited sources',
        'input_schema':{'title':'Read','type':'object','properties':{'title':{'type':'string'}}}}],
        'observations':{'x':{'title':'Actual source title','text':'Exact quoted  text'}}}
    original=deepcopy(context)
    result=trim_tool_schema_titles(context)
    assert context==original
    assert result['observations']==context['observations']
    assert result['available_tools'][0]['description']=='Read cited sources'
    assert 'title' in result['available_tools'][0]['input_schema']['properties']
