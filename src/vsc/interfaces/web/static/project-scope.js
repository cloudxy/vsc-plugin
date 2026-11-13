// Ownership and participation are directory filters, never a mutable session context.
export function directoryScope(value){return ['personal','team','created','participating'].includes(value)?value:'all';}
export function scopedProjects(rows,session,scope='all'){
  scope=directoryScope(scope);
  if(scope==='personal'||scope==='team')return rows.filter(row=>row.owner_kind===scope);
  if(scope==='created')return rows.filter(row=>row.created_by&&row.created_by===session.actor);
  if(scope==='participating')return rows.filter(row=>row.created_by!==session.actor&&(row.access_capabilities||[]).length>0);
  return rows;
}
export function directoryParams(session,scope='all'){
  scope=directoryScope(scope);const params=new URLSearchParams();
  if(scope==='personal'||scope==='team')params.set('owner_kind',scope);
  if(scope==='created'||scope==='participating')params.set('relation',scope);
  return params;
}
export function scopedDirectoryPath(path,session,scope){
  const [base,query='']=path.split('?'),params=new URLSearchParams(query);
  for(const [key,value]of directoryParams(session,scope))params.set(key,value);
  return base+(params.size?'?'+params:'');
}
