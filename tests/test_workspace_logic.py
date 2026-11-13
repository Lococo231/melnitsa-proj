"""Local-only tests of consistent horizons and recommendation diagnostics."""
import pytest
from workspace_logic import (analysis_hours,overview_series,recommendation,
                             recommendation_rows,journal_tables,initial_conditions)


def scenario():
    rows=[{'hour':0,'profile':'ЦЕМ I 42,5Н','throughput':70,'media_mass_t':150,
           'wear_cumulative_t':0,'piece_count':1000,'r008':1.5,'r0045':34,
           'blaine_proxy':3380,'rpm':15,'diameter_m':4,'violations':[], 'ok':True},
          {'hour':30,'profile':'ЦЕМ I 42,5Н','throughput':85,'media_mass_t':150.5,
           'wear_cumulative_t':0.5,'piece_count':1003,'r008':1.6,'r0045':34.5,
           'blaine_proxy':3370,'rpm':15,'diameter_m':4,'violations':[], 'ok':True},
          {'hour':2240,'profile':'ЦЕМ I 42,5Б','throughput':85,'media_mass_t':146,
           'wear_cumulative_t':5,'piece_count':1003,'r008':2,'r0045':35,
           'blaine_proxy':3500,'rpm':16,'diameter_m':4,'violations':['R0,08'], 'ok':False}]
    return {'hours':2240.,'hours_per_day':16.,'baseline':rows,
            'first_bad':rows[-1], 'cement_changes':[{'Час наработки':30,'Марка после':'ЦЕМ I 42,5Б'}]}


def test_every_overview_uses_full_timeline_and_integrated_q():
    r=scenario()
    lines=overview_series(r)
    assert len(lines)==6
    assert all(line['hours']==[0,30,2240] for line in lines)
    assert lines[1]['values']==[0,70*30,70*30+85*(2240-30)]
    assert lines[4]['values'][-1]==1003
    assert analysis_hours(r)==2240


def test_no_fake_success_when_q_not_modeled():
    r=scenario();r['first_bad']['violations']=['Производительность, т/ч']
    r['blocked_by_throughput']=True
    info=recommendation(r,{})
    assert not info['feasible']
    assert 'Q' in info['reason']


def test_combined_actions_and_auto_generated_journal():
    r=scenario()
    r['actions']=[{'hour':30.,'direction':'add','pieces':120,'tons':.4,
                  'valid_hours':2000.,'target':{'chamber':1,'type':'Шары','material':'Сталь','diameter_mm':70}},
                 {'hour':30.,'direction':'remove','pieces':50,'tons':.2,
                  'valid_hours':2000.,'target':{'chamber':2,'type':'Цильпебс','material':'Сталь','diameter_mm':20}}]
    info=recommendation(r,{})
    assert info['feasible'] and len(info['actions'])==2
    plan=recommendation_rows(r)
    assert [row['Штук'] for row in plan]==[120,50]
    assert all(row['Рабочий день']==2 for row in plan)
    journal=journal_tables(r)
    assert journal['cement'][0]['Час наработки']==30
    assert len(initial_conditions(r))==1


def test_rejects_mismatched_horizon():
    r=scenario();r['hours']=1500
    with pytest.raises(ValueError,match='не охватывают'):
        analysis_hours(r)
