-- Production snapshot of the OPD database, taken before Monday's report of double bookings (the schema is the one migrations 0001 to 0007 build).
-- It is real data: do not edit it. Three doctors' slots hold two Booked appointments each (same doctor_id, date and slot_at).

INSERT INTO doctors (id, name, department, phone, email, consultation_fee, room, availability, created_at) VALUES
  (1, 'Dr. Ananya Rao', 'Cardiology', '9212039962', 'a.rao@opd.example', 500, 'OPD 101', 'Available', '2026-09-01 09:00:00'),
  (2, 'Dr. Vikram Shah', 'General Medicine', '8216415116', 'v.shah@opd.example', 300, 'OPD 102', 'Available', '2026-09-01 09:00:00'),
  (3, 'Dr. Neha Kulkarni', 'General Medicine', '9983898678', 'n.kulkarni@opd.example', 300, 'OPD 204', 'Available', '2026-09-01 09:00:00'),
  (4, 'Dr. Farhan Ali', 'Pediatrics', '8408975520', 'f.ali@opd.example', 250, 'OPD 305', 'Available', '2026-09-01 09:00:00'),
  (5, 'Dr. Lakshmi Iyer', 'Dermatology', '9289848579', 'l.iyer@opd.example', 500, 'Block B 12', 'Available', '2026-09-01 09:00:00'),
  (6, 'Dr. Imran Qureshi', 'Orthopedics', '9810022334', 'i.qureshi@opd.example', 450, 'OPD 110', 'On leave', '2026-09-01 09:00:00');

INSERT INTO appointments (id, doctor_id, patient_name, patient_phone, date, slot_at, reason, status, created_at) VALUES
  (1, 1, 'Anjali Verma', '9842300972', '2026-10-13', '09:00', 'Chest discomfort', 'Booked', '2026-10-08 10:02:11'),
  (2, 1, 'Suresh Babu', '9890011223', '2026-10-13', '09:30', 'Follow-up ECG', 'Completed', '2026-10-08 10:15:40'),
  (3, 2, 'Farida Khan', '9765432100', '2026-10-12', '10:00', 'Fever and cough', 'Completed', '2026-10-08 11:30:02'),
  (4, 3, 'Mohan Lal', '9922334455', '2026-10-12', '10:30', 'Blood pressure check', 'Completed', '2026-10-08 12:01:55'),
  (5, 4, 'Baby Aarohi', '9011223344', '2026-10-12', '11:00', 'Vaccination', 'Completed', '2026-10-08 12:44:20'),
  (6, 5, 'Nisha Reddy', '9345671234', '2026-10-13', '11:30', 'Skin rash', 'Booked', '2026-10-09 09:05:31'),
  (7, 1, 'Rahul Deshmukh', '8523341498', '2026-10-14', '10:30', 'Annual check-up', 'Booked', '2026-10-10 09:12:05'),
  (8, 6, 'Gopal Singh', '9654321870', '2026-10-14', '12:00', 'Knee pain', 'Booked', '2026-10-09 14:10:00'),
  (9, 3, 'Pooja Menon', '9867123450', '2026-10-14', '14:00', 'Migraine', 'Cancelled', '2026-10-09 14:48:33'),
  (10, 5, 'Lata Gupta', '9811200345', '2026-10-12', '12:15', 'Acne review', 'Completed', '2026-10-08 15:20:19'),
  (11, 2, 'Imtiaz Ahmed', '9876001122', '2026-10-14', '15:00', 'Diabetes review', 'Booked', '2026-10-10 10:00:45'),
  (12, 4, 'Sana Sheikh', '9923456789', '2026-10-15', '11:00', 'Cold and sore throat', 'Booked', '2026-10-09 15:20:10'),
  (13, 1, 'Kishore Pillai', '9447712345', '2026-10-15', '09:00', 'Palpitations', 'Booked', '2026-10-10 11:25:14'),
  (14, 3, 'Rekha Joshi', '9890123456', '2026-10-15', '10:00', 'Back pain', 'Booked', '2026-10-10 12:40:00'),
  (15, 2, 'Kavita Patil', '9370011223', '2026-10-13', '09:30', 'Stomach ache', 'Booked', '2026-10-11 08:55:02'),
  (16, 5, 'Tanvi Shah', '9712345098', '2026-10-16', '15:30', 'Hair fall', 'Cancelled', '2026-10-10 16:05:09'),
  (17, 5, 'Varun Kohli', '9818123456', '2026-10-16', '15:30', 'Skin allergy', 'Cancelled', '2026-10-11 09:47:50'),
  (18, 4, 'Baby Ishaan', '9004455667', '2026-10-16', '10:00', 'Fever', 'Booked', '2026-10-11 10:30:12'),
  (19, 1, 'Meera Joshi', '9420099887', '2026-10-14', '10:30', 'Chest pain', 'Booked', '2026-10-12 11:40:31'),
  (20, 6, 'Harpreet Kaur', '9815566778', '2026-10-15', '11:30', 'Shoulder pain', 'Booked', '2026-10-12 12:02:27'),
  (21, 3, 'Rohit Jain', '9988776655', '2026-10-14', '14:00', 'Migraine follow-up', 'Booked', '2026-10-12 12:20:48'),
  (22, 2, 'Sneha Kulkarni', '9552233441', '2026-10-16', '09:00', 'Thyroid review', 'Booked', '2026-10-12 13:14:06'),
  (23, 5, 'Zoya Ansari', '9830011776', '2026-10-15', '14:30', 'Eczema', 'Booked', '2026-10-12 14:55:35'),
  (24, 4, 'Arjun Nair', '9446677889', '2026-10-15', '11:00', 'Cough for a week', 'Booked', '2026-10-13 10:05:44'),
  (25, 1, 'Leela Menon', '9847011223', '2026-10-16', '09:30', 'Blood pressure', 'Booked', '2026-10-13 10:50:21'),
  (26, 6, 'Deepak Verma', '9899001122', '2026-10-16', '12:00', 'Sprained ankle', 'Booked', '2026-10-13 11:12:59'),
  (27, 2, 'Dinesh Rao', '9741122334', '2026-10-13', '09:30', 'Stomach pain', 'Booked', '2026-10-12 16:18:09'),
  (28, 3, 'Asha Pawar', '9604455667', '2026-10-16', '10:30', 'Headache', 'Booked', '2026-10-13 12:30:03'),
  (29, 4, 'Baby Riya', '9028899001', '2026-10-16', '11:30', 'Ear ache', 'Booked', '2026-10-13 13:41:18'),
  (30, 5, 'Kabir Malhotra', '9810099887', '2026-10-16', '16:00', 'Mole check', 'Booked', '2026-10-13 14:22:37');
