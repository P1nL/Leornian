const roles = [
  ['author','出题人','出题',.119,.542,'W'], ['scope','课程审核','课程审',.244,.222,'NW'],
  ['level','难度审核','难度审',.454,.093,'N'], ['technical','技术审核','技术审',.614,.220,'N'],
  ['safety','安全审核','安全审',.787,.135,'NE'], ['release','发布判定','发布',.872,.438,'E'],
  ['stress','对抗审核','对抗审',.781,.704,'SE'], ['wording','歧义审核','歧义审',.600,.884,'S'],
  ['sandbox','沙盘验证','沙盘',.396,.751,'S'], ['blind','独立盲解','盲解',.211,.866,'SW'],
].map(([id,label,short,x,y,side]) => ({id,label,short,x,y,side}));

const routes = [
  ['author','blind',.040,-.015], ['author','sandbox',.015,-.034], ['blind','sandbox',-.008,-.053],
  ['sandbox','release',.055,.012], ['author','scope',.027,.010], ['scope','release',.023,-.009],
  ['author','level',-.018,-.036], ['level','release',-.010,.062], ['author','technical',.025,-.015],
  ['technical','release',.008,.029], ['author','wording',.023,-.043], ['wording','release',-.012,-.032],
  ['author','safety',.029,.038], ['safety','release',-.023,.008], ['author','stress',-.005,-.038],
  ['stress','release',-.024,-.025],
].map(([from,to,bowX,bowY])=>({from,to,bowX,bowY}));
const clamp = value => Math.max(0,Math.min(1,value));
function ease(value) { const part=clamp(value); return part*part*(3-2*part); }

export function createRelayScore(entries, executable=true) {
  const edges=routes.filter(edge=>executable || (edge.from!=='sandbox' && edge.to!=='sandbox'));
  const messages=entries.map(entry=>{
    let edge=-1;
    if (entry.from!==entry.to) {
      edge=edges.findIndex(route=>route.from===entry.from && route.to===entry.to);
      if (edge<0) edge=edges.push({from:entry.from,to:entry.to,bowX:.018,bowY:-.026})-1;
    }
    return {...entry,edge};
  });
  const beat=2.8, duration=messages.length*beat;
  function at(time) {
    if (!messages.length) return {index:-1,part:0,event:null,activeRole:'',phase:''};
    const within=Math.max(0,Math.min(duration,time));
    const index=Math.min(messages.length-1,Math.floor(within/beat+1e-9)), part=clamp(within/beat-index);
    const event=messages[index];
    return {index,part,event,activeRole:part<.57 ? event.from : event.to,
      head:ease((part-.10)/.47),tail:ease((part-.59)/.32),send:clamp(part/.20),receive:clamp((part-.57)/.32),
      phase:event.from===event.to ? event.action : part<.10 ? '发出' : part<.57 ? '传递中' : part<.59 ? '抵达' : part<.91 ? '收尾' : '已送达'};
  }
  return {roles,edges,messages,beat,duration,at};
}
