var d="__framer_force_showing_editorbar_since",E="__framer_editor_button_position",i="2147483647";var h=300;var x="__framer-editorbar-container",s="__framer-editorbar-label",a="__framer-editorbar-button",l="__framer-editorbar-button-tooltip-visible",u=`
#${x} {
    align-items: center;
    display: flex;
    gap: 8px;
    position: fixed;
    z-index: calc(${i});
    width: max-content;
    cursor: pointer;
}

#${s} {
    background-color: #111;
    border-radius: 8px;
    font-family: "Inter", "Inter-Regular", system-ui, Arial, sans-serif;
    font-size: 12px;
    height: fit-content;
    opacity: 0;
    padding: 4px 8px;
    transition: opacity 0.4s ease-out;
    font-weight: 500;
    flex-shrink: 0;
    position: fixed;
    width: max-content;
    pointer-events: none;
    user-select: none;
}

#${a} {
    all: unset;
    align-items: center;
    border-radius: 15px;
    display: flex;
    height: 30px;
    justify-content: center;
    width: 30px;
    flex-shrink: 0;
}

#${s}.${l} {
    opacity: 1;
}

#${s}, #${a} {
    backdrop-filter: blur(10px);
    background-color: rgba(34, 34, 34, 0.8);
    box-shadow: rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, rgba(0, 0, 0, 0.05) 0px 1px 0px 0px, rgba(255, 255, 255, 0.15) 0px 0px 0px 1px;
    color: #fff;
}
`,_=document.createElement("style");_.innerHTML=u;document.head.appendChild(_);function f(n){let e=window.__framer_editorBarDependencies;if(!e)throw new Error("Dependencies not found");if(e.__version<1||e.__version>3)throw new Error("Unsupported version");let t=e[n];if(!t)throw new Error("Dependency not found");return t}var{createElement:c,memo:m,useCallback:D,useEffect:y,useRef:L,useState:N,useLayoutEffect:g}=f("react");function B(n,e,t){let{children:r,...o}=e??{};return t!==void 0&&(o.key=t),c(n,o,r)}function C(n,e,t){let{children:r,...o}=e??{};return t!==void 0&&(o.key=t),c(n,o,...r)}var p=class extends Error{};function U(n,e){if(n)return;if(typeof e=="function")try{e=e()}catch{e="(assert message threw)"}typeof e=="string"&&e.length>2048&&(e=e.slice(0,2048)+"\u2026");let t=new p(e?"Assertion Error: "+e:"Assertion Error");if(t.stack)try{let r=t.stack.split(`
`);r[1]?.includes("assert")?(r.splice(1,1),t.stack=r.join(`
`)):r[0]?.includes("assert")&&(r.splice(0,1),t.stack=r.join(`
`))}catch{}throw t}function $(n,e){throw e instanceof Error?e:e!==void 0?new Error(String(e)):new Error(n?`Unexpected value: ${n}`:"Application entered invalid state")}export{d as a,E as b,i as c,h as d,x as e,s as f,a as g,l as h,f as i,m as j,D as k,y as l,L as m,N as n,U as o,$ as p,B as q,C as r};
//# sourceMappingURL=assets/local/8e396ad6a0dbe603.map
