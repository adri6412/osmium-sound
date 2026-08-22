import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import ScaledCanvas from './components/ScaledCanvas';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ScaledCanvas>
      <App />
    </ScaledCanvas>
  </React.StrictMode>
);

