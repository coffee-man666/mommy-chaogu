import{_ as c}from"./index-DvfJo_zJ.js";import{c as n,d as i,e as l,n as m,g as s,u as a,f as d,t as f,w as u,x,h as y}from"./index-Dgd79z8I.js";/**
 * @license lucide-vue-next v1.0.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const p=n("circle-alert",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["line",{x1:"12",x2:"12",y1:"8",y2:"12",key:"1pkeuh"}],["line",{x1:"12",x2:"12.01",y1:"16",y2:"16",key:"4dfq90"}]]),g={class:"text-sm text-muted-foreground"},B=i({__name:"ErrorState",props:{message:{default:"加载失败，请稍后再试"},compact:{type:Boolean,default:!1}},emits:["retry"],setup(t,{emit:r}){const o=r;return(k,e)=>(x(),l("div",{role:"alert",class:m(["flex flex-col items-center justify-center gap-3 text-center",t.compact?"py-6":"py-12"])},[s(a(p),{class:"size-8 text-destructive/70","aria-hidden":"true"}),d("p",g,f(t.message),1),s(a(c),{variant:"outline",size:"sm",onClick:e[0]||(e[0]=_=>o("retry"))},{default:u(()=>[...e[1]||(e[1]=[y("重试",-1)])]),_:1})],2))}});export{B as _};
