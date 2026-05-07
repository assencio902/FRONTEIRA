/**
 * database.js – In-memory / localStorage persistence layer
 * FRONTEIRA INTELIGENTE
 */

const DB = (function () {
  'use strict';

  const KEYS = {
    vehicles: 'fi_vehicles',
    crossings: 'fi_crossings',
    alerts: 'fi_alerts',
  };

  /* ---- Seed data ---- */
  const SEED_VEHICLES = [
    { id: 1, plate: 'ABC1234', model: 'Toyota Hilux', color: 'Branco',  year: 2021, owner: 'Carlos Mendes',       doc: '123.456.789-00', nationality: 'Brasileiro', status: 'Liberado',  obs: '' },
    { id: 2, plate: 'XYZ5678', model: 'Honda Civic',  color: 'Prata',  year: 2020, owner: 'Ana Paula Sousa',     doc: '987.654.321-00', nationality: 'Brasileira', status: 'Liberado',  obs: '' },
    { id: 3, plate: 'DEF9012', model: 'VW Gol',        color: 'Preto',  year: 2018, owner: 'Marcos Lima',         doc: '456.123.789-11', nationality: 'Brasileiro', status: 'Alerta',   obs: 'Suspeito de contrabando' },
    { id: 4, plate: 'GHI3456', model: 'Ford Ranger',   color: 'Azul',   year: 2022, owner: 'Pedro Santos',        doc: '321.654.987-22', nationality: 'Brasileiro', status: 'Bloqueado', obs: 'Veículo roubado – BO 2024/3456' },
    { id: 5, plate: 'JKL7890', model: 'Chevrolet S10', color: 'Vermelho', year: 2019, owner: 'Roberto Oliveira', doc: '654.321.000-33', nationality: 'Brasileiro', status: 'Liberado',  obs: '' },
    { id: 6, plate: 'MNO1122', model: 'Fiat Strada',   color: 'Branco', year: 2023, owner: 'Fernanda Costa',     doc: '111.222.333-44', nationality: 'Brasileira', status: 'Alerta',   obs: 'Investigação fiscal' },
    { id: 7, plate: 'PQR3344', model: 'Mitsubishi L200', color: 'Cinza', year: 2020, owner: 'Juan García',       doc: 'PAS-87654321',   nationality: 'Paraguaio',  status: 'Liberado',  obs: '' },
    { id: 8, plate: 'STU5566', model: 'Mercedes Sprinter', color: 'Branco', year: 2021, owner: 'Transport Ltda', doc: 'CNPJ 00.000.000/0001-00', nationality: 'Brasileiro', status: 'Bloqueado', obs: 'Carga não declarada – ANVISA' },
  ];

  function _load(key, seed) {
    try {
      const raw = localStorage.getItem(key);
      if (raw) return JSON.parse(raw);
    } catch (_) { /* ignore */ }
    _save(key, seed);
    return seed.map(function (item) { return Object.assign({}, item); });
  }

  function _save(key, data) {
    try {
      localStorage.setItem(key, JSON.stringify(data));
    } catch (_) { /* ignore */ }
  }

  /* ---- Vehicles ---- */
  function getVehicles() {
    return _load(KEYS.vehicles, SEED_VEHICLES);
  }

  function saveVehicles(list) {
    _save(KEYS.vehicles, list);
  }

  function findVehicleByPlate(plate) {
    const norm = plate.replace(/[^A-Z0-9]/gi, '').toUpperCase();
    return getVehicles().find(function (v) {
      return v.plate.replace(/[^A-Z0-9]/gi, '').toUpperCase() === norm;
    }) || null;
  }

  function _nextId(list) {
    return list.reduce(function (max, item) { return item.id > max ? item.id : max; }, 0) + 1;
  }

  function upsertVehicle(vehicle) {
    const list = getVehicles();
    const idx = list.findIndex(function (v) { return v.id === vehicle.id; });
    if (idx >= 0) {
      list[idx] = vehicle;
    } else {
      vehicle.id = _nextId(list);
      list.push(vehicle);
    }
    saveVehicles(list);
    return vehicle;
  }

  function deleteVehicle(id) {
    const list = getVehicles().filter(function (v) { return v.id !== id; });
    saveVehicles(list);
  }

  /* ---- Crossings ---- */
  function getCrossings() {
    return _load(KEYS.crossings, _generateSeedCrossings());
  }

  function saveCrossings(list) {
    _save(KEYS.crossings, list);
  }

  function addCrossing(crossing) {
    const list = getCrossings();
    crossing.id = _nextId(list);
    list.unshift(crossing);
    saveCrossings(list);
    return crossing;
  }

  /* ---- Alerts ---- */
  function getAlerts() {
    return _load(KEYS.alerts, []);
  }

  function saveAlerts(list) {
    _save(KEYS.alerts, list);
  }

  function addAlert(alert) {
    const list = getAlerts();
    alert.id = _nextId(list);
    alert.timestamp = new Date().toISOString();
    alert.read = false;
    list.unshift(alert);
    saveAlerts(list);
    return alert;
  }

  function markAlertRead(id) {
    const list = getAlerts().map(function (a) {
      if (a.id === id) return Object.assign({}, a, { read: true });
      return a;
    });
    saveAlerts(list);
  }

  function clearAlerts() {
    saveAlerts([]);
  }

  /* ---- Seed crossing data ---- */
  function _generateSeedCrossings() {
    var checkpoints = ['Norte', 'Sul', 'Leste', 'Oeste', 'Aeroporto'];
    var directions  = ['Entrada', 'Saída'];
    var plates = ['ABC1234', 'XYZ5678', 'DEF9012', 'GHI3456', 'JKL7890', 'MNO1122', 'PQR3344', 'STU5566'];
    var list = [];
    var now = Date.now();
    for (var i = 0; i < 40; i++) {
      var plate = plates[Math.floor(Math.random() * plates.length)];
      var v = SEED_VEHICLES.find(function (x) { return x.plate === plate; });
      var ts = new Date(now - i * 1000 * 60 * Math.floor(Math.random() * 30 + 5));
      list.push({
        id: i + 1,
        timestamp: ts.toISOString(),
        plate: plate,
        model: v ? v.model : 'Desconhecido',
        owner: v ? v.owner : 'Desconhecido',
        checkpoint: checkpoints[Math.floor(Math.random() * checkpoints.length)],
        direction: directions[Math.floor(Math.random() * directions.length)],
        status: v ? v.status : 'Alerta',
        agent: 'Agente Admin',
      });
    }
    return list;
  }

  return {
    getVehicles: getVehicles,
    saveVehicles: saveVehicles,
    findVehicleByPlate: findVehicleByPlate,
    upsertVehicle: upsertVehicle,
    deleteVehicle: deleteVehicle,
    getCrossings: getCrossings,
    addCrossing: addCrossing,
    getAlerts: getAlerts,
    addAlert: addAlert,
    markAlertRead: markAlertRead,
    clearAlerts: clearAlerts,
  };
})();
