import{b as t}from"./index-Dl2nEsin.js";function r(i=20){return t(`/api/agent/predictions?limit=${i}`).then(e=>e.predictions)}function a(){return t("/api/agent/predictions/stats")}export{a,r as g};
