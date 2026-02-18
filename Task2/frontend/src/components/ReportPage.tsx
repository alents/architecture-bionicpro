import React, { useState } from 'react';
import { useAuth } from '../useAuth';
import * as XLSX from 'xlsx';

const AUTH_API_URL = process.env.REACT_APP_AUTH_URL || 'http://localhost:3001';

interface EmgSensorData {
  user_id: number;
  prosthesis_type: string;
  muscle_group: string;
  signal_frequency: number;
  signal_duration: number;
  signal_amplitude: number;
  signal_time: string;
}

interface ReportResponse {
  user_id: number;
  period_start: string;
  period_end: string;
  total_records: number;
  data: EmgSensorData[];
  statistics: {
    total_records: number;
    avg_amplitude: number;
    max_amplitude: number;
    min_amplitude: number;
    avg_frequency: number;
    avg_duration: number;
    unique_prosthesis_types: number;
    unique_muscle_groups: number;
  };
}

const ReportPage: React.FC = () => {
  const { authenticated, loading, login } = useAuth();
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const downloadReport = async () => {
    try {
      setDownloading(true);
      setError(null);
      setSuccess(null);

      const startDate = '2025-01-01T00:00:00';
      const endDate = '2026-12-31T23:59:59';
      const limit = 10000;

      const url = `${AUTH_API_URL}/api/report?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}&limit=${limit}`;

      const response = await fetch(url, {
        credentials: 'include',
      });

      if (response.status === 401) {
        login(); // сессия протухла — на логин
        return;
      }

      if (!response.ok) {
        throw new Error(`Failed to fetch report: ${response.status} ${response.statusText}`);
      }

      const reportData: ReportResponse = await response.json();

      // Генерируем Excel файл
      generateExcelFile(reportData);

      setSuccess(`Отчет успешно скачан! Всего записей: ${reportData.total_records}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setDownloading(false);
    }
  };

  const generateExcelFile = (reportData: ReportResponse) => {
    // Создаем новую книгу
    const workbook = XLSX.utils.book_new();

    // Лист 1: Основные данные
    const dataSheet = XLSX.utils.json_to_sheet(
        reportData.data.map(item => ({
          'User ID': item.user_id,
          'Тип протеза': item.prosthesis_type,
          'Группа мышц': item.muscle_group,
          'Частота сигнала (Гц)': item.signal_frequency,
          'Длительность (мс)': item.signal_duration,
          'Амплитуда': item.signal_amplitude.toFixed(2),
          'Время сигнала': new Date(item.signal_time).toLocaleString('ru-RU'),
        }))
    );

    XLSX.utils.book_append_sheet(workbook, dataSheet, 'Данные сигналов');

    // Лист 2: Статистика
    const statsData = [
      { 'Параметр': 'User ID', 'Значение': reportData.user_id },
      { 'Параметр': 'Период (начало)', 'Значение': new Date(reportData.period_start).toLocaleString('ru-RU') },
      { 'Параметр': 'Период (конец)', 'Значение': new Date(reportData.period_end).toLocaleString('ru-RU') },
      { 'Параметр': 'Всего записей', 'Значение': reportData.statistics.total_records },
      { 'Параметр': 'Средняя амплитуда', 'Значение': reportData.statistics.avg_amplitude },
      { 'Параметр': 'Максимальная амплитуда', 'Значение': reportData.statistics.max_amplitude },
      { 'Параметр': 'Минимальная амплитуда', 'Значение': reportData.statistics.min_amplitude },
      { 'Параметр': 'Средняя частота (Гц)', 'Значение': reportData.statistics.avg_frequency },
      { 'Параметр': 'Средняя длительность (мс)', 'Значение': reportData.statistics.avg_duration },
      { 'Параметр': 'Уникальных типов протезов', 'Значение': reportData.statistics.unique_prosthesis_types },
      { 'Параметр': 'Уникальных групп мышц', 'Значение': reportData.statistics.unique_muscle_groups },
    ];

    const statsSheet = XLSX.utils.json_to_sheet(statsData);
    XLSX.utils.book_append_sheet(workbook, statsSheet, 'Статистика');

    // Генерируем имя файла с датой
    const fileName = `prosthesis_report_${new Date().toISOString().split('T')[0]}.xlsx`;

    // Скачиваем файл
    XLSX.writeFile(workbook, fileName);
  };

  if (loading) {
    return (
        <div className="flex items-center justify-center min-h-screen bg-gray-100">
          <div className="text-lg">Загрузка...</div>
        </div>
    );
  }

  if (!authenticated) {
    return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
          <div className="p-8 bg-white rounded-lg shadow-md">
            <h1 className="text-2xl font-bold mb-4">BionicPro Reports</h1>
            <p className="mb-6 text-gray-600">Для доступа к отчетам необходимо авторизоваться</p>
            <button
                onClick={login}
                className="px-6 py-3 bg-blue-500 text-white rounded hover:bg-blue-600 transition"
            >
              Войти
            </button>
          </div>
        </div>
    );
  }

  return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="p-8 bg-white rounded-lg shadow-md w-full max-w-md">
          <h1 className="text-2xl font-bold mb-2">Отчеты о работе протеза</h1>
          <p className="text-gray-600 mb-6 text-sm">
            Скачайте полный отчет со всеми данными о работе вашего протеза
          </p>

          <button
              onClick={downloadReport}
              disabled={downloading}
              className={`w-full px-6 py-3 bg-blue-500 text-white rounded hover:bg-blue-600 transition ${
                  downloading ? 'opacity-50 cursor-not-allowed' : ''
              }`}
          >
            {downloading ? (
                <span className="flex items-center justify-center">
              <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Формирование отчета...
            </span>
            ) : (
                'Скачать отчет (Excel)'
            )}
          </button>

          {error && (
              <div className="mt-4 p-4 bg-red-100 text-red-700 rounded border border-red-300">
                <strong>Ошибка:</strong> {error}
              </div>
          )}

          {success && (
              <div className="mt-4 p-4 bg-green-100 text-green-700 rounded border border-green-300">
                {success}
              </div>
          )}

          <div className="mt-6 p-4 bg-blue-50 rounded text-sm text-gray-700">
            <p className="font-semibold mb-2">Информация об отчете:</p>
            <ul className="list-disc list-inside space-y-1">
              <li>Данные всех сигналов за весь период</li>
              <li>Детальная статистика по показателям</li>
              <li>Формат: Microsoft Excel (.xlsx)</li>
              <li>Два листа: "Данные сигналов" и "Статистика"</li>
            </ul>
          </div>
        </div>
      </div>
  );
};

export default ReportPage;