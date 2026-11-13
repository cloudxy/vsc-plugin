// Ownership and participation are directory filters, never a mutable session context.
export function directoryScope(value){return ['personal','participating','team'].includes(value)?value:'personal';}
export function projectCategory(row,session){
  if(row.owner_kind==='team'||['studio','substudio'].includes(row.workspace_kind))return 'team';
  if(row.owner_actor&&session.actor&&row.owner_actor!==session.actor)return 'participating';
  return 'personal';
}
export function scopedProjects(rows,session,scope='all'){
  if(scope==='all')return rows;
  return rows.filter(row=>projectCategory(row,session)===directoryScope(scope));
}
export function directoryParams(session,scope='all'){
  return new URLSearchParams({project_category:directoryScope(scope)});
}
export function scopedDirectoryPath(path,session,scope){
  const [base,query='']=path.split('?'),params=new URLSearchParams(query);
  for(const [key,value]of directoryParams(session,scope))params.set(key,value);
  return base+(params.size?'?'+params:'');
}
