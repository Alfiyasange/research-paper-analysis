"""Download the 30-paper AI/ML dataset from arXiv into ./papers"""
import os, time, requests
PAPERS = {
 "1706.03762":"Attention Is All You Need","1810.04805":"BERT","2005.14165":"GPT-3",
 "2005.11401":"RAG (Lewis et al.)","2404.16130":"GraphRAG (Edge et al.)","2004.04906":"Dense Passage Retrieval",
 "1512.03385":"ResNet","1412.6980":"Adam","1406.2661":"GAN","1312.6114":"VAE",
 "1609.02907":"GCN","1710.10903":"GAT","1706.02216":"GraphSAGE","2010.11929":"ViT",
 "2103.00020":"CLIP","2106.09685":"LoRA","2307.09288":"Llama 2","2302.13971":"LLaMA",
 "2201.11903":"Chain-of-Thought","1907.11692":"RoBERTa","1910.10683":"T5","1908.10084":"Sentence-BERT",
 "2006.11239":"DDPM","1502.03167":"BatchNorm","2310.11511":"Self-RAG","2210.03629":"ReAct",
 "2302.04761":"Toolformer","2002.08909":"REALM","1603.09320":"HNSW (graph-based ANN)","1301.3781":"Word2Vec"}
for aid, name in PAPERS.items():
    out = f"papers/{aid}.pdf"
    if os.path.exists(out): continue
    r = requests.get(f"https://arxiv.org/pdf/{aid}", timeout=60)
    open(out, "wb").write(r.content); print("OK", aid, name); time.sleep(3)
