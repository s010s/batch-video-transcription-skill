import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aliyun_review_html import render

HARNESS=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const nodes={video:{currentTime:0,src:'',listeners:{},play(){return Promise.resolve()},addEventListener(n,f){this.listeners[n]=f}},turns:{children:[],append(b){this.children.push(b)}},sentences:{children:[],append(b){this.children.push(b)}}};
const document={getElementById(id){assert(nodes[id]);return nodes[id]},createElement(tag){assert.equal(tag,'button');return {textContent:'',classList:{toggle(){}}}}};
vm.runInNewContext(input.script,{document});
assert.equal(nodes.sentences.children.length,input.segments.length);
assert.equal(nodes.turns.children.length,input.turns.length);
input.segments.forEach((s,i)=>{assert(nodes.sentences.children[i].textContent.includes(s.text));nodes.sentences.children[i].onclick();assert.equal(nodes.video.currentTime,s.start)});
input.turns.forEach((t,i)=>{assert(nodes.turns.children[i].textContent.includes(t.texts.join('\n')));nodes.turns.children[i].onclick();assert.equal(nodes.video.currentTime,t.start)});
assert.equal(nodes.video.src,input.video);nodes.video.listeners.timeupdate();
console.log('JS runtime: '+input.segments.length+' sentences, '+input.turns.length+' turns, seek and safe text passed');
'''

class HtmlTests(unittest.TestCase):
    def check_html(self,html,data):
        scripts=re.findall(r'<script\b[^>]*>(.*?)</script\s*>',html,re.S|re.I)
        self.assertEqual(len(scripts),1)
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);script=d/'page.js';script.write_text(scripts[0]);harness=d/'runtime.cjs';harness.write_text(HARNESS)
            for script_text in scripts:
                script.write_text(script_text)
                subprocess.run(['node','--check',str(script)],check=True,capture_output=True)
            payload=d/'input.json';payload.write_text(json.dumps({'script':scripts[0],**data},ensure_ascii=False))
            result=subprocess.run(['node',str(harness),str(payload)],check=True,capture_output=True,text=True)
            print(result.stdout.strip())
    def test_chinese_quotes_newlines_backslash_script_close(self):
        text='中文 "双引号" \'单引号\'\n下一行\\路径 & </script><script>throw Error("XSS")</script>\u2028尾'
        segments=[{'start':1,'end':2,'speaker_id':0,'text':text}]
        turns=[{'start':1,'end':2,'sentence_indices':[0],'texts':[text]}]
        data={'video':'../../中文%20路径/a.MOV','segments':segments,'turns':turns}
        self.check_html(render(data),data)
if __name__=='__main__':unittest.main()
