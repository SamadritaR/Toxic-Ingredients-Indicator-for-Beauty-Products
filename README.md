#  Toxic Ingredients Indicator for Beauty Products  

An **AI-powered Streamlit application** that identifies toxic or harmful ingredients in skincare and beauty products.  
Users can paste an ingredient list into the app, and it will instantly flag risky compounds, provide safety explanations, and generate an overall product safety score.  

This project demonstrates the **intersection of AI/ML, NLP, and product management** — from building the model pipeline to designing PRDs and testing usability with real users.  

---

##  My Role  
I built this project end-to-end, focusing on:  
- Designing the **NLP pipeline** to parse ingredient lists.  
- Creating structured **product requirement documents (PRDs)** to guide development.  
- Defining **personas and prioritization (MoSCoW)** for roadmap planning.  
- Conducting **usability testing with peers** to validate the user experience.  
- Deploying the working prototype on **Streamlit** for easy accessibility.  

---

##  Technical Execution  
1. **Data Collection**  
   - Gathered datasets from **CosIng EU database, EWG Skin Deep, and Kaggle cosmetic ingredients**.  
   - Compiled a **knowledge base** with ingredient names, synonyms, toxicity levels, and safety rationales.  

2. **Data Labeling**  
   - Classified ingredients as **High Concern, Moderate Concern, or Safe** using FDA + EWG guidelines.  

3. **Model Training**  
   - **Baseline:** Logistic Regression + TF-IDF (with spaCy tokenization).  
   - **Advanced:** Transformer models (BERT, DistilBERT) for improved classification of complex multi-word compounds.  
   - Achieved an **F1-score of ~0.88** with the hybrid transformer-based approach.  

4. **Prototype Deployment**  
   - Built a **Streamlit app** with:  
     - Text input box for ingredient lists.  
     - Highlighting of toxic terms in **red**.  
     - Tooltip explanations with sources.  
     - An **overall product risk meter** (Safe → High Risk).  

---

##  Product Workflow  
- Drafted a **PRD** defining MVP features:  
  - Ingredient parsing + toxicity flagging.  
  - Risk categorization tooltips.  
  - Overall product toxicity score.  
- Applied **MoSCoW prioritization**:  
  - Must-have → flagging toxic ingredients.  
  - Should-have → product safety meter.  
  - Could-have → safer alternatives suggestion.  
- Defined **personas**: skincare enthusiasts, dermatologists, regulators.  

---

##  Data-Driven Decision Making  
- **Evaluation metrics:** Precision, Recall, F1-score.  
- Prioritized **recall for High Concern** class (false negatives too costly).  
- **Error analysis:** Discovered misclassification of some natural extracts → retrained model with balanced samples.  
- Iteratively improved thresholds → final model achieved **F1-score ~0.88**.  

---

##  User-Centric Development  
- Conducted peer usability testing (n=10).  
- **Feedback:**  
  - “List is helpful, but I want a quick overall score.”  
- **Iteration:**  
  - Added **Product Risk Score Meter** (visual gauge).  
- **Result:**  
  - Reduced average evaluation time from **5 minutes of web searches → <30 seconds in the app**.  

---

##  Key Features  
- Paste ingredient list → get instant **toxicity analysis**.  
- **Highlighting & Tooltips** → clear explanations for each flagged ingredient.  
- **Overall Safety Score** → product-level risk assessment.  
- **Source-Backed Transparency** → FDA, EU CosIng, EWG references.  
- Simple, intuitive UI built with **Streamlit**.  

---

##  Tech Stack  
- **Languages/Frameworks:** Python, Streamlit, Flask (optional backend)  
- **ML/NLP:** scikit-learn, spaCy, transformers (BERT, DistilBERT)  
- **Data:** FDA, EU CosIng, EWG Skin Deep, Kaggle datasets  
- **Deployment:** Docker, Heroku/AWS (planned)  

---

##  Roadmap  
- [x] MVP with rules-based KB matching  
- [x] ML pipeline (Logistic Regression + TF-IDF)  
- [x] Transformer integration (DistilBERT)  
- [x] Streamlit interface with highlights + tooltips  
- [ ] Suggest safer ingredient alternatives  
- [ ] Deploy cloud version with Docker/Heroku  
- [ ] Add user feedback loop for retraining  

---
---

## Disclaimer

This tool is for educational purposes only.
It is not a substitute for medical or regulatory advice. Always consult dermatologists or official authorities for health-related guidance.
