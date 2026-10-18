import { afterEach, beforeEach, expect, mock, spyOn, test } from 'bun:test';
import { createElement } from 'react';
import { act, create } from 'react-test-renderer';
import { api } from '../src/lib/api';
import { operations } from '../src/lib/operations';

const part = ({children, ...props}: any) => createElement('div', props, children);
mock.module('../src/components/ServiceGraph', () => ({ServiceGraph: part}));
mock.module('../src/components/ServicePanel', () => ({ServicePanel: part}));
mock.module('../src/components/ui/tabs', () => ({Tabs:part,TabsList:part,TabsTrigger:part,TabsContent:part}));
mock.module('../src/components/ui/select', () => ({Select:part,SelectTrigger:part,SelectValue:part,SelectContent:part,SelectGroup:part,SelectItem:part}));
const { OperationsWorkspace } = await import('../src/components/os/OperationsWorkspace');
const onApplicationChange = () => {};
let renderer: ReturnType<typeof create> | undefined;
const originalSocket = globalThis.WebSocket;
const originalLocation = globalThis.location;

function view(applicationId: string) {
  return {application:{application_id:applicationId},topology:{state:'available',observed_at:new Date().toISOString(),
    services:[],edges:[],dependency_state:'available'},open_incidents:0,anomalies_24h:0,active_findings:0,
    recent_activity:[],recent_service_changes:[],sources:[]};
}
function props(applicationId: string) {
  return {role:'viewer',applicationId,onApplicationChange,onOpenApplications:()=>{},onClose:()=>{}};
}
beforeEach(() => {
  globalThis.WebSocket = class { close() {} } as any;
  globalThis.location = {origin:'http://localhost:5173'} as any;
  spyOn(api,'applications').mockResolvedValue([{application_id:'one',name:'One'}, {application_id:'two',name:'Two'}] as any);
  for (const name of ['incidents','anomalies','experiments','evaluations','scenarios'] as const) {
    spyOn(operations,name).mockResolvedValue([]);
  }
});
afterEach(() => {
  act(()=>renderer?.unmount());
  renderer=undefined;
  globalThis.WebSocket=originalSocket;
  globalThis.location=originalLocation;
  mock.restore();
});

test('application switching requests current data while previous request is pending', async () => {
  let release: (value:any)=>void = ()=>{};
  const pending = new Promise(resolve=>{release=resolve;});
  const overview = spyOn(operations,'overview').mockImplementation(async app=>app==='one' ? pending as any : view(app) as any);
  await act(async()=>{renderer=create(<OperationsWorkspace {...props('one')} />);});
  await act(async()=>{renderer!.update(<OperationsWorkspace {...props('two')} />);});
  expect(overview.mock.calls.map(c=>c[0])).toEqual(['one','two']);
  await act(async()=>{release({...view('one'),open_incidents:987654});});
  expect(JSON.stringify(renderer!.toJSON())).not.toContain('987654');
});

test('unavailable operations do not display fabricated healthy counts', async () => {
  spyOn(operations,'overview').mockRejectedValue(new Error('Source unavailable'));
  await act(async()=>{renderer=create(<OperationsWorkspace {...props('one')} />);});
  const output=JSON.stringify(renderer!.toJSON());
  expect(output).toContain('Source unavailable');
  expect(output).toContain('Unavailable');
  expect(output).not.toContain('All systems operational');
});
