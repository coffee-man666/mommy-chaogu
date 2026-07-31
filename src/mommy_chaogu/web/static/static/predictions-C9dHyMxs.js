import{b as t}from"./index-C0nx-0V1.js";function r(i=20){return t(`/api/agent/predictions?limit=${i}`).then(e=>e.predictions)}function a(){return t("/api/agent/predictions/stats")}export{a,r as g};
