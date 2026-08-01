import{_ as c}from"./index-eQuFriTr.js";import{c as n,d as i,e as l,n as m,g as s,u as a,f as d,t as y,w as f,y as u,h as p}from"./index-DXI32qCb.js";/**
 * @license lucide-vue-next v1.0.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const x=n("circle-alert",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["line",{x1:"12",x2:"12",y1:"8",y2:"12",key:"1pkeuh"}],["line",{x1:"12",x2:"12.01",y1:"16",y2:"16",key:"4dfq90"}]]),g={class:"text-sm text-muted-foreground"},B=i({__name:"ErrorState",props:{message:{default:"加载失败，请稍后再试"},compact:{type:Boolean,default:!1}},emits:["retry"],setup(t,{emit:r}){const o=r;return(k,e)=>(u(),l("div",{role:"alert",class:m(["flex flex-col items-center justify-center gap-3 text-center",t.compact?"py-6":"py-12"])},[s(a(x),{class:"size-8 text-destructive/70","aria-hidden":"true"}),d("p",g,y(t.message),1),s(a(c),{variant:"outline",size:"sm",onClick:e[0]||(e[0]=_=>o("retry"))},{default:f(()=>[...e[1]||(e[1]=[p("重试",-1)])]),_:1})],2))}});export{B as _};
