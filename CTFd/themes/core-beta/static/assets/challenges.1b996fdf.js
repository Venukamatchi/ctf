import{m as s,C as l,h as r,T as h,d as g,M as c}from"./index.1d7c7e9f.js";function o(e){let a=new DOMParser().parseFromString(e,"text/html");return a.querySelectorAll('a[href*="://"]').forEach(i=>{i.setAttribute("target","_blank")}),a.documentElement.outerHTML}window.Alpine=s;s.store("challenge",{data:{view:""}});s.data("Hint",()=>({id:null,html:null,async showHint(e){if(e.target.open){let a=(await l.pages.challenge.loadHint(this.id)).data;if(a.content)this.html=o(a.html);else if(await l.pages.challenge.displayUnlock(this.id)){let i=await l.pages.challenge.loadUnlock(this.id);if(i.success){let d=(await l.pages.challenge.loadHint(this.id)).data;this.html=o(d.html)}else e.target.open=!1,l._functions.challenge.displayUnlockError(i)}else e.target.open=!1}}}));s.data("Challenge",()=>({id:null,next_id:null,submission:"",tab:null,solves:[],response:null,async init(){r()},getStyles(){let e={"modal-dialog":!0};try{switch(l.config.themeSettings.challenge_window_size){case"sm":e["modal-sm"]=!0;break;case"lg":e["modal-lg"]=!0;break;case"xl":e["modal-xl"]=!0;break;default:break}}catch(t){console.log("Error processing challenge_window_size"),console.log(t)}return e},async init(){r()},async showChallenge(){new h(this.$el).show()},async showSolves(){this.solves=await l.pages.challenge.loadSolves(this.id),this.solves.forEach(e=>(e.date=g(e.date).format("MMMM Do, h:mm:ss A"),e)),new h(this.$el).show()},getNextId(){return s.store("challenge").data.next_id},async nextChallenge(){let e=c.getOrCreateInstance("[x-ref='challengeWindow']");e._element.addEventListener("hidden.bs.modal",t=>{s.nextTick(()=>{this.$dispatch("load-challenge",this.getNextId())})},{once:!0}),e.hide()},async submitChallenge(){this.response=await l.pages.challenge.submitChallenge(this.id,this.submission),await this.renderSubmissionResponse()},async renderSubmissionResponse(){this.response.data.status==="correct"&&(this.submission=""),this.$dispatch("load-challenges")}}));s.data("ChallengeBoard",()=>({loaded:!1,challenges:[],challenge:null,async init(){if(this.challenges=await l.pages.challenges.getChallenges(),this.loaded=!0,window.location.hash){let e=decodeURIComponent(window.location.hash.substring(1)),t=e.lastIndexOf("-");if(t>=0){let n=[e.slice(0,t),e.slice(t+1)][1];await this.loadChallenge(n)}}},getCategories(){const e=[];this.challenges.forEach(t=>{const{category:a}=t;e.includes(a)||e.push(a)});try{const t=l.config.themeSettings.challenge_category_order;if(t){const a=new Function(`return (${t})`);e.sort(a())}}catch(t){console.log("Error running challenge_category_order function"),console.log(t)}return e},getChallenges(e){const t=this.challenges.filter(a=>a.category===e);try{const a=l.config.themeSettings.challenge_order;if(a){const n=new Function(`return (${a})`);t.sort(n())}}catch(a){console.log("Error running challenge_order function"),console.log(a)}return t},async loadChallenges(){this.challenges=await l.pages.challenges.getChallenges()},async loadChallenge(e){await l.pages.challenge.displayChallenge(e,t=>{t.data.view=o(t.data.view),s.store("challenge").data=t.data,s.nextTick(()=>{let a=c.getOrCreateInstance("[x-ref='challengeWindow']");a._element.addEventListener("hidden.bs.modal",n=>{history.replaceState(null,null," ")},{once:!0}),a.show(),history.replaceState(null,null,`#${t.data.name}-${e}`)})})}}));s.start();
