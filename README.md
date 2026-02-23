# FRONTEIRA INTELIGENTE

Sistema de Controle de Fronteira com Reconhecimento de Placas (LPR)

## Visão Geral

**FRONTEIRA INTELIGENTE** é uma aplicação web de controle de fronteira que integra:

- 📊 **Dashboard** – estatísticas em tempo real de passagens, liberações, alertas e bloqueios com gráficos interativos
- 📷 **Scanner LPR** – interface de reconhecimento automático de placas com simulação de câmera e consulta instantânea à base de dados
- 🚗 **Cadastro de Veículos** – gerenciamento completo de veículos com status (*Liberado*, *Alerta*, *Bloqueado*)
- 📋 **Registro de Passagens** – histórico completo de todas as passagens com filtros e exportação para CSV
- 🔔 **Central de Alertas** – notificações em tempo real para veículos em alerta ou bloqueados

## Como Usar

1. Abra o arquivo `index.html` em qualquer navegador moderno (Chrome, Firefox, Edge, Safari).
2. Não é necessário servidor — a aplicação roda localmente usando `localStorage` para persistência.

## Tecnologias

- HTML5 / CSS3 / JavaScript (vanilla)
- [Bootstrap 5.3](https://getbootstrap.com/)
- [Bootstrap Icons 1.11](https://icons.getbootstrap.com/)
- [Chart.js 4.4](https://www.chartjs.org/)

## Estrutura do Projeto

```
FRONTEIRA/
├── index.html        # Página principal
├── css/
│   └── style.css     # Estilos customizados
├── js/
│   ├── database.js   # Camada de dados (localStorage)
│   └── app.js        # Lógica da aplicação
└── README.md
```

## Funcionalidades do LPR

- Simulação de captura automática (câmera) com animação de varredura
- Consulta de placa por digitação manual ou captura simulada
- Exibição imediata de status, proprietário, modelo e observações
- Registro automático de cada passagem com geração de alerta para veículos suspeitos ou bloqueados

